#!/usr/bin/env python
# Copyright 2015 Cisco Systems, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
#
# Author: Alec Hothan
# ---------------------------------------------------------


from pandas import DataFrame
import pandas
import numpy as np

from perfmap_common import get_time_span_usec

# For sorting
# 'CSR.1.vcpu0' => '0001.CSR.vcpu0'
def normalize_task_name(task):
    tokens = task.split('.')
    if len(tokens) > 1:
        # extract the service chain
        chain = tokens[1]
        try:
            chain = int(tokens[1])
            res = '%02d' % (chain)
            tokens.pop(1)
            return res + '.' + '.'.join(tokens)
        except ValueError:
            pass
    return task

def normalize_df_task_name(df):
    df['task_name'] = df.apply(lambda row: normalize_task_name(row['task_name']), axis=1)

def filter_df_core(df, task_re, remove_cpu=False):
    # remove unneeded columns
    df = df.drop(['next_pid', 'pid', 'usecs', 'next_comm'], axis=1)
    if remove_cpu:
        df = df.drop('cpu', axis=1)

    # filter out all events except the switch events
    df = df[df.event == 'sched__sched_switch']
    df = df.drop('event', axis=1)
    df = df[df['task_name'].str.match(task_re)]
    return df

def get_coremaps(dfds, cap_time_usec, task_re):
    '''
    coremaps =  [
        { "run":"run1", "coremap": [
             { "task":"vnf1", "counts":[[0,5.5,231], [1,15.5,231], [2,25.5,21],
                                        [3,35.5,231],[4,45.8,415], [5,55.5,231],
                                        [6,65,231], [7,75.5,231],[8,85.5,231],
                                        [9,95.5,231]]},
             { "task":"vnf2", "counts":[[2,70.5,91], [31,45.1,152]]},
             { "task":"all tasks", "counts":[[1,10.5,231], [2,30.5,21], [4,21.8,415],[31,45.1,152]]}
             ],
             "minsw": 5, "maxsw": 415
        },
        { "run":"run2", "coremap": [
             { "task":"vnf1", "counts":[[4,40.5,51], [7,0.8,215]]},
             { "task":"vnf2", "counts":[[30,35.1,62]]},
             { "task":"all tasks", "counts":[[4,40.5,51], [7,0.8,215],[30,35.1,62]]
             ],
             "minsw": 51, "maxsw": 215
        }
    ]
    '''
    coremaps = []
    for dfd in dfds:
        df = dfd.df
        time_span_usec = get_time_span_usec(df)

        # remove unneeded columns
        df = filter_df_core(df, task_re)

        # at this point we have a df that looks like this:
        #         task_name  cpu  duration
        # 0     ASA.1.vcpu0    8      7954
        # 1     ASA.1.vcpu0    9      5475
        # 2     ASA.1.vcpu0    9      1000
        # 3     ASA.1.vcpu0   11     12391
        # 4     ASA.1.vcpu0   12     21025
        # 5     ASA.1.vcpu0   13      6447
        # etc...
        if len(df) == 0:
            print
            print 'No selection matching "%s"' % (task_re)
            return None
        gb = df.groupby(['task_name', 'cpu'], as_index=False)

        # because we only show percentages, there is no need to apply the multiplier
        # add duration values
        df = gb.aggregate(np.sum)
        #         task_name  cpu  duration
        # 0     ASA.1.vcpu0    8      7954
        # 1     ASA.1.vcpu0    9      6475
        # 2     ASA.1.vcpu0   11     12391

        # Add a % column
        df['percent'] = np.round((df['duration'] * 100) / time_span_usec, 2)

        # many core-pinned system tasks have a duration of 0 (swapper, watchdog...)
        df.fillna(100, inplace=True)
        df.drop(['duration'], axis=1, inplace=True)

        # count number of rows with same task and cpu
        dfsw = DataFrame(gb.size())
        dfsw.reset_index(inplace=True)
        dfsw.rename(columns={0: 'count'}, inplace=True)
        # adjust context switch count if the requested cap time is > time_span
        if dfd.multiplier > 1.0:
            dfsw['count'] = (dfsw['count'].astype(int) * dfd.multiplier).astype(int)
        min_count = dfsw['count'].min()
        max_count = dfsw['count'].max()
        #       task_name  cpu  count
        # 0  ASA.01.vcpu0    8   9853
        # 1  ASA.01.vcpu0    9    348
        # 1  ASA.01.vcpu0   11    619

        # Merge the 2 df using the task_name/cpu as the joining key
        dfm = pandas.merge(df, dfsw, how="left", on=['task_name', 'cpu'])

        alltasks_label = 'all tasks'

        # calculate the sum of all percent and switches per task
        dfallcores = dfm.drop('cpu', axis=1)
        gball = dfallcores.groupby('task_name')
        dfallcores = gball.aggregate(np.sum)
        dfallcores['percent'] = np.round(dfallcores['percent'], 2)
        dfallcores['task_name'] = dfallcores.index
        dfallcores['cpu'] = '0-31'

        # sort all the tasks in reverse order (without the 'all tasks')
        task_list = gball.groups.keys()
        task_list.sort(reverse=True)
        task_list.append(alltasks_label)
        # concatenate the 2 dfs
        dfm = pandas.concat([dfm, dfallcores], ignore_index=True)

        # calculate the sum of all percent and switches per cpu
        dfalltasks = dfm.drop('task_name', axis=1)
        gball = dfalltasks.groupby('cpu')
        dfalltasks = gball.aggregate(np.sum)
        dfalltasks['task_name'] = alltasks_label
        dfalltasks['cpu'] = dfalltasks.index
        dfalltasks['percent'] = np.round(dfalltasks['percent'], 2)
        # concatenate all dfs
        dfm = pandas.concat([dfm, dfalltasks], ignore_index=True)

        # generate the data structure for the jinja template
        cml = []
        gb = dfm.groupby('task_name')

        for task in task_list:
            counts = []
            dfg = gb.get_group(task)
            for index, row in dfg.iterrows():
                counts.append([row['cpu'], row['percent'], row['count']])
            cml.append({"task": task, "counts": counts})

        coremap = {"run": dfd.short_name, "coremap": cml, "extent": str([min_count, max_count])}
        coremaps.append(coremap)
    return coremaps

def get_cpu_sw_map(dfds, cap_time_usec, task_re):
    df_list = []
    dfsw_list = []
    for dfd in dfds:
        df = filter_df_core(dfd.df, task_re, True)
        # at this point we have a set of df that look like this:
        #         task_name  duration
        # 0     ASA.1.vcpu0      7954
        # 1     ASA.1.vcpu0      5475
        # 2     ASA.1.vcpu0      4151
        if df.empty:
            continue
        gb = df.groupby('task_name', as_index=False)

        # sum all duration for each task
        df = gb.aggregate(np.sum)
        if dfd.multiplier > 1.0:
            df['duration'] = (df['duration'] * dfd.multiplier).astype(int)
        df['percent'] = ((df['duration'] * 100 * 10) // cap_time_usec) / 10
        if len(dfds) > 1:
            df['task_name'] = df['task_name'] + '.' + dfd.short_name
        df_list.append(df)

        # count number of rows with same task and cpu
        dfsw = DataFrame(gb.size())
        dfsw.reset_index(inplace=True)
        dfsw.rename(columns={0: 'count'}, inplace=True)

        if dfd.multiplier > 1.0:
            dfsw['count'] = (dfsw['count'] * dfd.multiplier).astype(int)
        else:
            dfsw['count'] = dfsw['count'].astype(int)
        dfsw_list.append(dfsw)

    df = pandas.concat(df_list)
    df = df.drop('duration', axis=1)
    dfsw = pandas.concat(dfsw_list)
    df = pandas.merge(df, dfsw, on='task_name')
    # Result:
    #             task_name  percent  count
    # 0  ASA.01.vcpu0.1x218     72.0  1998
    # 1  ASA.01.vcpu0.2x208     61.8  2128
    # 2  ASA.02.vcpu0.2x208     58.9  2177

    # transform this into a dict where the key is the task_name and the value
    # is a list [percent, count]
    return df.set_index('task_name').T.to_dict('list')
