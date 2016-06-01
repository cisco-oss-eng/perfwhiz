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


def get_groupby(df, task_re):
    # if task is a number it is considered to be a pid ID
    # if text it is a task name
    try:
        tid = int(task_re)
        # tid given
        df = df[df['pid'] == tid]
        # a groupby with only 1 group since we already filtered on the pid
        gb = df.groupby('pid')
    except ValueError:
        # task given: find corresponding tid
        df = df[df['task_name'].str.match(task_re)]
        gb = df.groupby('task_name')

    return gb

def get_sw_kvm_events(dfd, task_re):
    '''
    :param df:
    :param task_re:
    :return:
        { "usecs_min": 129,
          "usecs_max": 1873291,
          "usecs_duration_max": 287312,
          "task_events": [
             {"task": "CSR",
              "events":
                { "kvm_exit": [ [0,1,30], [20, 421, 30], ...],
                  "kvm_entry": [],
                  "sched__sched_switch": [],
                  "sched__sched_stat_sleep": []
                }
             },...
          ]
        }

    '''
    gb = get_groupby(dfd.df, task_re)
    nb_tasks = len(gb.groups)
    if nb_tasks == 0:
        raise RuntimeError('No selection matching: ' + task_re)
    event_list = ['sched__sched_switch', 'sched__sched_stat_sleep', 'kvm_exit', 'kvm_entry']
    task_list = gb.groups.keys()
    task_list.sort()
    duration_max = -1

    task_event_list = []
    for task in task_list:
        dfg = gb.get_group(task)
        dfg = dfg.drop(['task_name', 'pid', 'next_pid', 'next_comm'], axis=1)
        dfg = dfg[dfg.columns[::-1]]
        task_events = {}
        for event in event_list:
            events = []
            dfe = dfg[dfg.event == event]
            duration_max = max(duration_max, dfe['duration'].max())
            dfe = dfe.drop('event', axis=1)

            # limit to 50k events
            if len(dfe) > 50000:
                dfe = dfe[:50000]
                print 'Series for %s display truncated to 50000 events' % (event)
            itt = dfe.itertuples(index=False)
            for row in itt:
                # each row is a tuple with usec, duration and core
                events.append(list(row))
            task_events[event] = events
        task_event_list.append({"task": task, "events": task_events})
    return {'run': dfd.short_name,
            'task_events': task_event_list,
            'usecs_min': dfd.from_usec,
            'usecs_max': dfd.to_usec,
            'usecs_duration_max': duration_max}
