import numpy as np
import pandas as pd
import threading
import os
from threading import Lock
from influxdb import InfluxDBClient
from optimal_downsampling_manager.decision_type import Decision
from optimal_downsampling_manager.resource_predictor.estimate_table import Degraded_IATable, get_context, DownTimeTable, DownRatioTable, Degraded_Q_IATable, get_month_and_day
import argparse
import time  
import time
import sys
import random

###  preselected matrix
# time_matrix = np.array([
#     [0,45,24,12,10,3,2,0],
#     [0,41,32,15,6,4,2,0],
#     [0,50,23,14,8,4,1,0],
#     [0,94,50,23,15,3,3,0],
#     [0,46,43,35,29,6,1,0],
#     [0,59,23,17,12,6,2,0]
# ])

# space_matrix = np.array([
#     [200,100,50,40,45,23,21,0],
#     [120,100,36,27,22,17,10,0],
#     [250,150,74,59,45,12,8,0],
#     [320,150,88,70,49,34,14,0],
#     [250,74,28,24,19,15,14,0],
#     [100,64,31,29,25,18,12,0]
# ])

# profit_matrix = np.array([
#     [100,74,32,15,42,22,2,0],
#     [94,45,30,25,15,6,32,0],
#     [120,77,45,41,64,47,22,0],
#     [94,54,12,45,30,19,14,0],
#     [41,21,45,33,30,18,21,0],
#     [45,26,33,19,26,21,15,0]
# ])

# pickup_quality = [
#     0,0,0,0,0,0
# ]

# clip_number = len(pickup_quality)


MAX_INT = pow(2,64)
ANALY_LIST=["illegal_parking0","people_counting"]

O_v = None # MB
delta_d = None ## second
O_i = None ## High watermark 
algo = None 
scale_ratio = None ## scale ratio fo video size  

import yaml
with open('configuration_manager/config.yaml','r') as yamlfile:
    data = yaml.load(yamlfile,Loader=yaml.FullLoader)


DBclient = InfluxDBClient(data['global']['database_ip'], data['global']['database_port'], 'root', 'root', data['global']['database_name'])
result_DBclient = InfluxDBClient(data['global']['database_ip'], data['global']['database_port'], 'root', 'root', "exp_storage")



pre_d_selected = None
time_matrix = None
space_matrix = None
profit_matrix = None
clip_number = 0 

result = DBclient.query('SELECT * FROM DownTimeTable')
TimeTable = pd.DataFrame(list(result.get_points(measurement="DownTimeTable")))

result = DBclient.query('SELECT * FROM DownRatioTable')
RatioTable = pd.DataFrame(list(result.get_points(measurement="DownRatioTable")))

result = DBclient.query('SELECT * FROM Degraded_Q_IATable')
Degraded_Q_IATable = pd.DataFrame(list(result.get_points(measurement="Degraded_Q_IATable")))

result = DBclient.query('SELECT * FROM MaxAnalyticTargetNumber')
MaxTargetTable = pd.DataFrame(list(result.get_points(measurement="MaxAnalyticTargetNumber")))

result = DBclient.query('SELECT * FROM down_result')
RawSizeTable = pd.DataFrame(list(result.get_points(measurement="down_result")))

result = DBclient.query('SELECT * FROM visual_features_entropies_PCA_normalized')
PCATable = pd.DataFrame(list(result.get_points(measurement="visual_features_entropies_PCA_normalized")))


def get_time_sum(pickup_quality, time_matrix):
    time_sum = 0
    for key, value in enumerate(pickup_quality):
        time_sum += time_matrix[key][value]
    return time_sum

def get_space_sum(pickup_quality, space_matrix):
    space_sum = 0
    for k, i in enumerate(pickup_quality):
        space_sum  += space_matrix[k][i]
    return space_sum
    
def get_profit_sum(pickup_quality, profit_matrix):
    profit_sum = 0
    for key, value in enumerate(pickup_quality):
        profit_sum += profit_matrix[key][value]
    return profit_sum



def P_EF(pickup_quality):
    flag = 0
    global pre_d_selected, time_matrix, space_matrix, profit_matrix, clip_number
    space_sum = get_space_sum(pickup_quality, space_matrix)
    while space_sum > O_v:
        if np.all(np.array(pickup_quality)==len(pre_d_selected)-1):
            break

        flag = flag%len(pickup_quality)
        if pickup_quality[flag] == 0: # make the quality to (24, 500)
            pickup_quality[flag] = 1
            space_sum = space_sum - space_matrix[flag][0] + space_matrix[flag][1]
        elif pickup_quality[flag] == len(pre_d_selected)-1:
            flag+=1
            continue
        else: # delete the file
            space_sum = space_sum - space_matrix[flag][pickup_quality[flag]]
            pickup_quality[flag] = len(pre_d_selected)-1

        
        # print(pickup_quality,space_sum)
        flag += 1


    print("EF Results :")

    time_sum = get_time_sum(pickup_quality, time_matrix) 
    space_sum = get_space_sum(pickup_quality, space_matrix)
    profit_sum = get_profit_sum(pickup_quality, profit_matrix)

    print("pickup_quality",pickup_quality)
    print("time_sum", time_sum)
    print("space_sum", space_sum)
    print("profit_sum", profit_sum)

    pickup_quality_transformed = []
    for i in pickup_quality:
        pickup_quality_transformed.append([pre_d_selected[i][0], pre_d_selected[i][1]])
    # print("pickup_quality_transformed", pickup_quality_transformed)
    return time_sum, space_sum, profit_sum, pickup_quality_transformed

def P_EFR(pickup_quality):
    flag = 0
    global pre_d_selected, time_matrix, space_matrix, profit_matrix, clip_number, O_i, O_v, delta_d
    space_sum = get_space_sum(pickup_quality, space_matrix)

    print("init ", pickup_quality, space_sum)
    while space_sum > O_v:
        
        # print(flag)
        if np.all(np.array(pickup_quality)==len(pre_d_selected)-1):
            break

        flag = flag%len(pickup_quality)
        if pickup_quality[flag] == 0: # make the quality to (12, 1000)
            pickup_quality[flag] = 2
        elif pickup_quality[flag] == len(pre_d_selected)-1:
            flag+=1
            continue
        else: ## has been degrade, need to be deleted / already is 12 fps, delete it
            space_sum = space_sum - space_matrix[flag][2]*2 
            pickup_quality[flag] = len(pre_d_selected)-1

        # print(pickup_quality,space_sum)
        flag += 1
    
    print("EFR Results :")
    time_sum = get_time_sum(pickup_quality, time_matrix) 
    space_sum = get_space_sum(pickup_quality, space_matrix)
    profit_sum = get_profit_sum(pickup_quality, profit_matrix)

    print("pickup_quality",pickup_quality)
    print("time_sum (Have no data)", time_sum)
    print("space_sum", space_sum)
    print("profit_sum", profit_sum)

    pickup_quality_transformed = []
    for i in pickup_quality:
        pickup_quality_transformed.append([pre_d_selected[i][0], pre_d_selected[i][1]])
    print("pickup_quality_transformed", pickup_quality_transformed)
    return time_sum, space_sum, profit_sum, pickup_quality_transformed

def P_FIFO(pickup_quality):
    flag = 0

    global pre_d_selected, time_matrix, space_matrix, profit_matrix, clip_number, O_i, O_v, delta_d
    space_sum = get_space_sum(pickup_quality, space_matrix)

    while space_sum > O_v:
        if np.all(np.array(pickup_quality)==len(pre_d_selected)-1):
            break

        flag = flag%len(pickup_quality)

        if pickup_quality[flag] == len(pre_d_selected)-1:
            flag+=1
            continue
        else: # delete the file
            space_sum = space_sum - space_matrix[flag][pickup_quality[flag]]
            pickup_quality[flag] = len(pre_d_selected)-1

        
        # print(pickup_quality,space_sum)
        flag += 1

    # pre_d_selected = np.array(pre_d_selected)
    # output_qualuity =  pre_d_selected[pickup_quality]
    # print("FIFO Final :", output_qualuity)
    print("FIFO Results :")
    time_sum = get_time_sum(pickup_quality, time_matrix) 
    space_sum = get_space_sum(pickup_quality, space_matrix)
    profit_sum = get_profit_sum(pickup_quality, profit_matrix)

    print("pickup_quality",pickup_quality)
    print("time_sum (Have no data)", time_sum)
    print("space_sum", space_sum)
    print("profit_sum", profit_sum)

    pickup_quality_transformed = []
    for i in pickup_quality:
        pickup_quality_transformed.append([pre_d_selected[i][0], pre_d_selected[i][1]])
    print("pickup_quality_transformed", pickup_quality_transformed)
    return time_sum, space_sum, profit_sum, pickup_quality_transformed

def P_heuristic(pickup_quality):

    global time_matrix, space_matrix, profit_matrix, pre_d_selected, clip_number, O_i, O_v, delta_d
    space_sum = get_space_sum(pickup_quality, space_matrix)
    time_sum = 0
    time_matrix_sorted = np.zeros((clip_number, len(pre_d_selected)))
    space_matrix_sorted = np.zeros((clip_number, len(pre_d_selected)))
    profit_matrix_sorted = np.zeros((clip_number, len(pre_d_selected)))

    

    argsort_space_matrix = np.argsort((-space_matrix))
    for i in range(clip_number):
        time_matrix_sorted[i] = time_matrix[i][argsort_space_matrix[i]]
        space_matrix_sorted[i] = space_matrix[i][argsort_space_matrix[i]]
        profit_matrix_sorted[i] = profit_matrix[i][argsort_space_matrix[i]]



    profit_list = []

    for c, q in enumerate(pickup_quality):
        s = space_matrix_sorted[c][q]

        if s>0 and pickup_quality[c] < profit_matrix_sorted.shape[1]:
            profit_list.append((c, profit_matrix_sorted[c][q]/s)) 

    while space_sum > O_v or time_sum < delta_d:
        
        victim_c = min(profit_list, key= lambda x: x[1])
        # print(profit_list)


        c = victim_c[0]
        profit_list.remove(victim_c)
        d = pickup_quality[c] + 1
        
        
        if pickup_quality[c]==space_matrix_sorted.shape[1]-1:
            print("the victim can not be downsample anymore")
            continue

        
        space_sum = space_sum - space_matrix_sorted[c][pickup_quality[c]] + space_matrix_sorted[c][d] 
        
        time_sum = 0
        for t_key,v in enumerate(pickup_quality):
            time_sum += time_matrix_sorted[t_key][v]


        s = space_matrix_sorted[c][d]

        if s > 0: ## make sure the last one is zero
            profit_list.append((c, profit_matrix_sorted[c][d]/s)) 


        pickup_quality[c] = d
        # print(c, pickup_quality[c])
        if len(profit_list) == 0:
            print("np video")
            break
        # print(pickup_quality)
       
        # print(space_sum, time_sum)


    # Convert to the correct order
    for k_i, i in enumerate(pickup_quality):
        pickup_quality[k_i] = argsort_space_matrix[k_i][i]
        

    time_sum = get_time_sum(pickup_quality, time_matrix_sorted) 
    space_sum = get_space_sum(pickup_quality, space_matrix_sorted)
    profit_sum = get_profit_sum(pickup_quality, profit_matrix_sorted)

    print("pickup_quality",pickup_quality)
    print("time_sum", time_sum)
    print("space_sum", space_sum)
    print("profit_sum", profit_sum)

    pickup_quality_transformed = []
    for i in pickup_quality:
        pickup_quality_transformed.append([pre_d_selected[i][0], pre_d_selected[i][1]])
    print("pickup_quality_transformed", pickup_quality_transformed)
    return time_sum, space_sum, profit_sum, pickup_quality_transformed
    

def P_opt(pickup_quality):
    global time_matrix, space_matrix, profit_matrix, pre_d_selected, clip_number, O_i, O_v, delta_d, scale_ratio
    space_matrix = np.floor(space_matrix * scale_ratio).astype(np.int8) ## Cause the running time and memeory issues, we enlarge the scale fo space to reduce to size of array
    time_matrix = np.floor(time_matrix * scale_ratio).astype(np.int8)
    print("Start P_opt...")
    opt_state = np.zeros((O_v+1, delta_d+1, clip_number+1), dtype=np.float16)

    init_quality = len(pre_d_selected)-1
    pickup_quality_knapsack = np.add(np.zeros((O_v+1, delta_d+1, clip_number+1, clip_number), dtype=np.int8), init_quality)

    # pickup_quality_knapsack = np.array([[[[(len(pre_d_selected)-1) for i in range(clip_number)] for i in range(clip_number+1)] for j in range(delta_d+1)] for k in range(O_v+1)])

    min_time = np.zeros(clip_number)
    min_space = np.zeros(clip_number)
    for c in range(clip_number):
        min_time[c] = time_matrix[c].min()
        min_space[c] = space_matrix[c].min()

    for o in range(1, O_v+1):
        for delta in range(1, delta_d+1):
            for c in range(1, clip_number+1):
                if delta>=min_time[c-1] and o>=min_space[c-1]:
                    remain_time_array = np.subtract(delta, time_matrix[c-1])
                    remain_space_array = np.subtract(o, space_matrix[c-1])
                    
                    candidatad_quality_arg_time = np.argwhere(remain_time_array>=0).reshape(-1)
                    candidatad_quality_arg_space = np.argwhere(remain_space_array>=0).reshape(-1)

                    candidatad_quality_arg = np.intersect1d(candidatad_quality_arg_time, candidatad_quality_arg_space)

                    
                    ## Don't choose better quality
                    if pickup_quality[c-1]!=0:
                        og_quality = pickup_quality[c-1]
                        invalaid_quality = np.where(candidatad_quality_arg<og_quality)
                        candidatad_quality_arg = np.delete(candidatad_quality_arg, invalaid_quality)
                    
                    # if some clip has non zero execution time
                    if candidatad_quality_arg.shape[0]>0:
                        remain_time_idx = remain_time_array[candidatad_quality_arg].reshape(-1)
                        remain_space_idx = remain_space_array[candidatad_quality_arg].reshape(-1)

                        
                        # print(profit_matrix[c-1][candidatad_quality_arg])
                        tmp_profit_matrix = list()
                        for q_i in range(len(candidatad_quality_arg)):                                
                            tmp_profit_matrix.append(opt_state[remain_space_idx[q_i]][remain_time_idx[q_i]][c-1] + profit_matrix[c-1][candidatad_quality_arg[q_i]])
            
                        tmp_max_idx = np.argmax(np.array(tmp_profit_matrix))
                        tmp_max = tmp_profit_matrix[tmp_max_idx]
    
                    else:
                        tmp_max = 0
                else:
                    tmp_max = 0

                if opt_state[o][delta][c-1] >= tmp_max: # not pickup any quality for c
                    opt_state[o][delta][c] = opt_state[o][delta][c-1]
                    pickup_quality_knapsack[o][delta][c] = pickup_quality_knapsack[o][delta][c-1]
                else: # pick the length of c
                    opt_state[o][delta][c] = tmp_max
                    pickup_quality_knapsack[o][delta][c] = pickup_quality_knapsack[remain_space_idx[tmp_max_idx]][remain_time_idx[tmp_max_idx]][c-1]
                    pickup_quality_knapsack[o][delta][c][c-1] = candidatad_quality_arg[tmp_max_idx]

    pickup_quality = pickup_quality_knapsack[-1][-1][-1].astype(int)

    time_sum = 0
    for key, value in enumerate(pickup_quality):
        time_sum += time_matrix[key][value]
    time_sum /= scale_ratio

    space_sum = 0
    for key, value in enumerate(pickup_quality):
        space_sum += space_matrix[key][value]
    space_sum /= scale_ratio 
    profit_sum = 0
    for key, value in enumerate(pickup_quality):
        profit_sum += profit_matrix[key][value]


    print("pickup_quality", pickup_quality)
    print("time_sum", time_sum)
    print("space_sum", space_sum)
    print("profit_sum", profit_sum)
    print("profit_sum_opt", opt_state[-1][-1][-1])

    pickup_quality_transformed = []
    for i in pickup_quality:
        pickup_quality_transformed.append([pre_d_selected[i][0], pre_d_selected[i][1]])
    print("pickup_quality_transformed", pickup_quality_transformed)
    return time_sum, space_sum, profit_sum, pickup_quality_transformed

def log_database(algo, day, hour, total_video_size):

    total_video_ia= list(result_DBclient.query("SELECT sum(ia) FROM video_in_server_"+algo))[0][0]['sum']
    total_video_clip_number= list(result_DBclient.query("SELECT count(size) FROM video_in_server_"+algo))[0][0]['count']
    print("total_video_ia: %f, total_video_clip_number: %d, total_video_size: %f:"%(total_video_ia, total_video_clip_number, total_video_size))
    json_body = [
            {
                "measurement":"log_every_hour_"+algo,
                "tags": {
                    "day": str(day),
                    "hour": str(hour)
                },
                "fields": {
                    "total_size": float(total_video_size),
                    "total_clips_number": int(total_video_clip_number),
                    "total_ia": float(total_video_ia)
                }
            }
        ]
    result_DBclient.write_points(json_body)

def main(args):
    
    global pre_d_selected, time_matrix, space_matrix, profit_matrix, clip_number, algo, O_i, O_v, delta_d, scale_ratio
    O_v = int(args.ov); delta_d = int(args.delta); O_i = int(args.oi); algo = str(args.algo); scale_ratio = float(args.scale)
    pre_d_selected = [[24,1000],[24,500],[12,500],[12,100],[6,100],[6,10],[1,10],[0,0]]

    ### Read all videos
    day_flag = 0 ## Record the read videos position
    total_video_size = 0
    total_video_ia = 0
    video_list = []
    video_in_server = [] 
    start = 9
    end = 16
    sample_length_full_quality_info_df = None
    full_length_sample_quality_info_df = None
    full_info_df = None
    for d in range(start, end):
        name = "raw_11_"+str(d)
        result = DBclient.query("SELECT * FROM "+name)
        video_list.extend(list(result.get_points(measurement=name)))

        sample_quality_measurement_name = "sample_quality_alltarget_inshot_11_"+str(d)
        sample_measurement_name = "analy_sample_result_inshot_11_" + str(d)
        full_measurement_name = "analy_complete_result_inshot_11_" + str(d)
        
        result = DBclient.query('SELECT * FROM '+sample_quality_measurement_name)
        full_length_sample_quality_info_df = pd.concat([full_length_sample_quality_info_df, pd.DataFrame(list(result.get_points(measurement=sample_quality_measurement_name)))])
        result = DBclient.query('SELECT * FROM '+sample_measurement_name)
        sample_length_full_quality_info_df = pd.concat([sample_length_full_quality_info_df, pd.DataFrame(list(result.get_points(measurement=sample_measurement_name)))])
        result = DBclient.query('SELECT * FROM '+full_measurement_name)
        full_info_df = pd.concat([full_info_df, pd.DataFrame(list(result.get_points(measurement=full_measurement_name)))])

 

    while day_flag < len(video_list):
        ## Collecting new videos 
        print("total_video_size", total_video_size, "total_ia_in_server", total_video_ia)
        while total_video_size < (O_i/scale_ratio):
            new_coming_video_name = video_list[day_flag]['name']
            new_coming_video_size = list(DBclient.query("SELECT * FROM down_result where \"name\"=\'"+new_coming_video_name+"\'"))[0][0]['raw_size']
            total_video_size += new_coming_video_size
            new_coming_video_SLE_length = list(result_DBclient.query("SELECT * FROM L_opt_exp_length where \"name\"=\'"+new_coming_video_name+"\'"))[0][0]
            new_coming_video_info = (full_info_df.loc[(full_info_df['name']==new_coming_video_name) & (full_info_df['a_type']=='illegal_parking0')]['target'].iloc[0] / MaxTargetTable.loc[(MaxTargetTable['a_type']=='illegal_parking0')]['value'].iloc[0]) 
            new_coming_video_info += (full_info_df.loc[(full_info_df['name']==new_coming_video_name) & (full_info_df['a_type']=='people_counting')]['target'].iloc[0] / MaxTargetTable.loc[(MaxTargetTable['a_type']=='people_counting')]['value'].iloc[0]) 
            new_coming_video_info += PCATable.loc[PCATable['name']==new_coming_video_name].iloc[0]['value']

            json_body = [
                            {
                                "measurement":"video_in_server_"+algo,
                                "tags": {
                                    "name":str(new_coming_video_name)
                                },
                                "fields": {
                                    "fps": int(24),
                                    "bitrate": int(1000),
                                    "size": float(new_coming_video_size),
                                    "ill_param": int(new_coming_video_SLE_length['ill_param']),
                                    "peo_param": int(new_coming_video_SLE_length['peo_param']),
                                    "ia": float(new_coming_video_info)
                                }
                            }
                        ]
            result_DBclient.write_points(json_body, time_precision='ms')
            
            ## log database every hour
            log_month, log_day = get_month_and_day(new_coming_video_name)
            _, log_hour = get_context(new_coming_video_name)
            log_database(algo, log_day, log_hour, total_video_size)
            day_flag+=1
            if day_flag >= len(video_list):
                print("Finish "+algo+" Evaluation!!!")
                sys.exit()

        print("Before total_video_size %f MB"%(total_video_size))
        print("Trigger DDM")
        ## Init to downsample videos
        pickup_quality = []
        length_from_SLE = []
        day_list = list(result_DBclient.query("SELECT * FROM video_in_server_"+algo))[0]
        day_list_copy = day_list.copy()

        for d_l in day_list:
            pickup_quality.append(pre_d_selected.index([int(d_l['fps']), int(d_l['bitrate'])]))
            length_from_SLE.append([d_l['ill_param'], d_l['peo_param']])

        
        clip_number = len(day_list)
        time_matrix = np.zeros((clip_number, len(pre_d_selected)))
        space_matrix = np.zeros((clip_number, len(pre_d_selected)))
        profit_matrix = np.zeros((clip_number, len(pre_d_selected)))

        for i in range(time_matrix.shape[0]):
            # print(day_list[i]['name'])
            day_idx, time_idx = get_context(day_list[i]['name'])
            

            if length_from_SLE[i][0] == 0:
                ill_info = 0
            elif length_from_SLE[i][0] == 1:
                ill_info = full_info_df.loc[(full_info_df['name']==day_list[i]['name']) & (full_info_df['a_type']=='illegal_parking0')]['target'].iloc[0]
                ill_info /= MaxTargetTable.loc[(MaxTargetTable['a_type']=='illegal_parking0')]['value'].iloc[0]
            else:
                ill_info = sample_length_full_quality_info_df.loc[(sample_length_full_quality_info_df['name']==day_list[i]['name']) & (sample_length_full_quality_info_df['a_type']=='illegal_parking0') & (sample_length_full_quality_info_df['a_parameter']==str(length_from_SLE[i][0]))]['target'].iloc[0]
                ill_info/= MaxTargetTable.loc[(MaxTargetTable['a_type']=='illegal_parking0')]['value'].iloc[0]
    
            
            if length_from_SLE[i][1] == 0:
                peo_info = 0
            elif length_from_SLE[i][1] == 1:
                peo_info = full_info_df.loc[(full_info_df['name']==day_list[i]['name']) & (full_info_df['a_type']=='people_counting')]['target'].iloc[0]
                peo_info /= MaxTargetTable.loc[(MaxTargetTable['a_type']=='people_counting')]['value'].iloc[0]
            else:
                peo_info = sample_length_full_quality_info_df.loc[(sample_length_full_quality_info_df['name']==day_list[i]['name']) & (sample_length_full_quality_info_df['a_type']=='people_counting') & (sample_length_full_quality_info_df['a_parameter']==str(length_from_SLE[i][1]))]['target'].iloc[0]
                peo_info /= MaxTargetTable.loc[(MaxTargetTable['a_type']=='people_counting')]['value'].iloc[0]
            

            target_size_row = RawSizeTable.loc[(RawSizeTable['name']==day_list[i]['name'])].iloc[0]['raw_size']
            target_time_row = TimeTable.loc[(TimeTable['day_of_week'] == str(day_idx)) & (TimeTable['time_of_day'] == str(time_idx))]
            target_ratio_row = RatioTable.loc[(RatioTable['day_of_week'] == str(day_idx)) & (RatioTable['time_of_day'] == str(time_idx))]  
            target_degraded_q_row = Degraded_Q_IATable.loc[(Degraded_Q_IATable['day_of_week'] == str(day_idx)) & (Degraded_Q_IATable['time_of_day'] == str(time_idx))]
            pca_value = PCATable.loc[PCATable['name']==day_list[i]['name']].iloc[0]['value']


            for j in range(time_matrix.shape[1]-1):
                if pickup_quality[i] == j:
                    down_time = 0
                    down_ratio = 1
                    peo_degraded_Q_ratio = 1
                    ill_degraded_Q_ratio = 1
                elif pickup_quality[i] > j:
                    down_time = MAX_INT
                    down_ratio = MAX_INT
                    peo_degraded_Q_ratio = -MAX_INT
                    ill_degraded_Q_ratio = -MAX_INT
                else:
                    down_time = target_time_row.loc[(target_time_row['fps'] == str(pre_d_selected[j][0])) & (target_time_row['bitrate'] == str(pre_d_selected[j][1]))]['value']
                    down_ratio = target_ratio_row.loc[(target_time_row['fps'] == str(pre_d_selected[j][0])) & (target_ratio_row['bitrate'] == str(pre_d_selected[j][1]))]['value']
                    peo_degraded_Q_ratio = target_degraded_q_row.loc[(target_degraded_q_row['fps'] == str(pre_d_selected[j][0])) & (target_degraded_q_row['bitrate'] == str(pre_d_selected[j][1])) & (target_degraded_q_row['a_type'] == 'people_counting')]['value'].iloc[0]
                    ill_degraded_Q_ratio = target_degraded_q_row.loc[(target_degraded_q_row['fps'] == str(pre_d_selected[j][0])) & (target_degraded_q_row['bitrate'] == str(pre_d_selected[j][1])) & (target_degraded_q_row['a_type'] == 'illegal_parking0')]['value'].iloc[0]
                
                time_matrix[i][j] = down_time 
                space_matrix[i][j] = target_size_row * down_ratio

                profit_matrix[i][j] += peo_info * peo_degraded_Q_ratio
                profit_matrix[i][j] += ill_info * ill_degraded_Q_ratio
            
            profit_matrix[i] += pca_value
            time_matrix[i][j+1] = 0
            space_matrix[i][j+1] = 0
            profit_matrix[i][j+1] = 0
        
        algo_start_time = time.time()
        if algo=='EF':
            time_sum, space_sum, profit_sum, pickup_quality_transformed = P_EF(pickup_quality)
        elif algo=='EFR':
            time_sum, space_sum, profit_sum, pickup_quality_transformed = P_EFR(pickup_quality)
        elif algo=='FIFO':
            time_sum, space_sum, profit_sum, pickup_quality_transformed = P_FIFO(pickup_quality)
        elif algo=='heuristic':
            time_sum, space_sum, profit_sum, pickup_quality_transformed = P_heuristic(pickup_quality)
        elif algo=='opt':
            time_sum, space_sum, profit_sum, pickup_quality_transformed = P_opt(pickup_quality)
        else:
            print("Wrong Algo Name!!!")
        algo_exec_time = time.time() - algo_start_time
        print("Algo %s takes %f seconds"%(algo, algo_exec_time))

        ### Record the downsample Results: video_in_server/Downsampling result of different Algo
        for i, d in enumerate(day_list):            
            if pickup_quality_transformed[i][0]==0 and pickup_quality_transformed[i][1]==0:
                result_DBclient.query("DELETE FROM video_in_server_"+algo+" where \"name\"=\'" + d['name'] + "\'")
                print("Delete clip %s"%(d['name']))
            elif int(pickup_quality_transformed[i][0]) == int(day_list_copy[i]['fps']) and int(pickup_quality_transformed[i][1]) == int(day_list_copy[i]['bitrate']):
                ## remain the quality, do nothing 
                continue
            else: ## update the quality of video in server
                result_fps = str(pickup_quality_transformed[i][0]); result_bitrate = str(pickup_quality_transformed[i][1])

                down_result = list(DBclient.query("SELECT * FROM down_result where \"name\"=\'"+d['name']+"\' AND \"fps\"=\'"+str(result_fps)+"\' AND \"bitrate\"=\'"+str(result_bitrate)+"\'"))[0][0]
                result_size = down_result['raw_size'] * down_result['ratio']
                try:
                    preserved_video_info_ill = full_length_sample_quality_info_df.loc[(full_length_sample_quality_info_df['name']==day_list[i]['name']) & (full_length_sample_quality_info_df['a_type']=='illegal_parking0') & (full_length_sample_quality_info_df['fps']==result_fps) & (full_length_sample_quality_info_df['bitrate']==result_bitrate)]['target'].iloc[0]
                    preserved_video_info_ill /= MaxTargetTable.loc[(MaxTargetTable['a_type']=='illegal_parking0')]['value'].iloc[0]
                except:
                    print("Not found sampled_video: name:", day_list[i]['name'], "fps:", result_fps, "bitrate:", result_bitrate)
                    preserved_video_info_ill = 0
                try:
                    preserved_video_info_peo = full_length_sample_quality_info_df.loc[(full_length_sample_quality_info_df['name']==day_list[i]['name']) & (full_length_sample_quality_info_df['a_type']=='people_counting') & (full_length_sample_quality_info_df['fps']==result_fps) & (full_length_sample_quality_info_df['bitrate']==result_bitrate)]['target'].iloc[0]
                    preserved_video_info_peo /= MaxTargetTable.loc[(MaxTargetTable['a_type']=='people_counting')]['value'].iloc[0]
                except:
                    print("Not found sampled_video: name:", day_list[i]['name'], "fps:", result_fps, "bitrate:", result_bitrate)
                    preserved_video_info_peo = 0
                try:
                    preserved_video_info_pca = PCATable.loc[PCATable['name']==day_list[i]['name']].iloc[0]['value']
                except:
                    preserved_video_info_pca = 0
                preserved_video_info = preserved_video_info_ill+ preserved_video_info_peo + preserved_video_info_pca
                

                origin_video_info = (full_info_df.loc[(full_info_df['name']==day_list[i]['name']) & (full_info_df['a_type']=='illegal_parking0')]['target'].iloc[0] / MaxTargetTable.loc[(MaxTargetTable['a_type']=='illegal_parking0')]['value'].iloc[0]) 
                origin_video_info += (full_info_df.loc[(full_info_df['name']==day_list[i]['name']) & (full_info_df['a_type']=='people_counting')]['target'].iloc[0] / MaxTargetTable.loc[(MaxTargetTable['a_type']=='people_counting')]['value'].iloc[0]) 
                origin_video_info += PCATable.loc[PCATable['name']==day_list[i]['name']].iloc[0]['value']
                
                if preserved_video_info > origin_video_info:
                    print("origin_video_info", origin_video_info, "preserved_video_info", preserved_video_info)

                json_body = [
                            {
                                "measurement":"video_in_server_"+algo,
                                "tags": {
                                    "name":str(d['name'])
                                },
                                "time":d['time'],
                                "fields": {
                                    "fps": int(pickup_quality_transformed[i][0]),
                                    "bitrate": int(pickup_quality_transformed[i][1]),
                                    "size": float(result_size),
                                    "ill_param":int(d['ill_param']),
                                    "peo_param": int(d['peo_param']),
                                    "ia": float(preserved_video_info)
                                }
                            }
                        ]
                result_DBclient.write_points(json_body, time_precision='ms') ## Note that the time precision should be ms, or it will be a new insertion
                
        trigger_month, trigger_day = get_context(day_list[-1]['name'])
        _, trigger_hour = get_month_and_day(day_list[-1]['name'])
        ## Get the result total_video_size, this value will be reuse in next iteration!
        total_video_size= list(result_DBclient.query("SELECT sum(size) FROM video_in_server_"+algo))[0][0]['sum']
        total_video_ia= list(result_DBclient.query("SELECT sum(ia) FROM video_in_server_"+algo))[0][0]['sum']

        json_body = [
                        {
                            "measurement":"P_exp_result_"+algo,
                            "tags": {
                                "trigger_month": str(trigger_month),
                                "trigger_day": str(trigger_day),
                                "trigger_hour": str(trigger_hour)
                            },
                            "fields": {
                                "time_sum": float(time_sum),
                                "expect_space_sum": float(space_sum),
                                "expect_profit_sum": float(profit_sum),
                                "fact_space_sum": float(total_video_size),   
                                "fact_profit_sum": float(total_video_ia),
                                "algo_exec_time": float(algo_exec_time)
                            }
                        }
                    ]
        result_DBclient.write_points(json_body)
        print("result total_video_size", total_video_size)

def drop_measurement_if_exist(table_name):
    result = result_DBclient.query('SELECT * FROM '+table_name)
    result_point = list(result.get_points(measurement=table_name))
    if len(result_point)>0:
        result_DBclient.query('DROP MEASUREMENT '+table_name)

if __name__=="__main__":

    parser = argparse.ArgumentParser(description='Parameter for P')

    parser.add_argument('-d','--delta', required=True, help='Downsampling Deadline (sec)')
    parser.add_argument('-v','--ov', required=True, help='Target Watermark (MB)')
    parser.add_argument('-i','--oi', required=True, help='Trigger Watermark (MB)')
    parser.add_argument('-a','--algo', required=True, help='Downsampling Strategy (EF, EFR, FIFO, heuristic, opt)')
    parser.add_argument('-s','--scale', required=True, help='scale_ratio')

    args = parser.parse_args()
    drop_measurement_if_exist("P_exp_result_"+str(args.algo))
    drop_measurement_if_exist("log_every_hour_"+str(args.algo))
    drop_measurement_if_exist("video_in_server_"+str(args.algo))
    
    main(args)