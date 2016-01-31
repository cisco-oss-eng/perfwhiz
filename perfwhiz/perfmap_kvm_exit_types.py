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

import pandas
from pandas import DataFrame
from perfmap_common import output_svg_html
from perfmap_common import get_time_span_usec

import itertools
import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np

from jinja2 import Environment
from jinja2 import FileSystemLoader
import time
from __init__ import __version__

# Use the matplotlib pastel1 palette for exit codes that do not have an assigned color
default_palette = [colors.rgb2hex(rgb) for rgb in plt.cm.Pastel1(np.linspace(0, 1, 10))]
default_color_palette = itertools.cycle(default_palette)
# This palette is extracted from colorbrewer2 qualitative palette with 10 colors
assigned_palette = ['#a6cee3', '#1f78b4', '#ff7f00', '#33a02c', '#fb9a99',
                    '#e31a1c', '#fdbf6f', '#b2df8a', '#cab2d6', '#6a3d9a']
assigned_index = 0
def assigned_color():
    global assigned_index
    res = assigned_palette[assigned_index]
    # limited to 10 for now
    assigned_index += 1
    return res

# KVM exit reasons
# Intel64 and IA32 Architecture Software Developer's Manual Vol 3B, System Programming Guide Part 2
# Appendix I
# The key is the numeric exit reason value
# The value is a list containing the exit reason clear text and an assigned color
# Most common exits are assigned a fixed color in order to avoid uneven color assignment across charts
# Exits without any assigned color will get a random assignment from a fixed color palette
# (with some possibly of near match with assigned colors unfortunately)
KVM_EXIT_REASONS = {
    0: ['Exception or NMI', assigned_color()],    #
    1: ['External Interrupt', assigned_color()],  #
    2: ['Triple Fault'],
    3: ['INIT'],
    4: ['Startup IPI'],
    5: ['I/O SMI (System Mgmt Interrupt)'],
    6: ['Other SMI'],
    7: ['Interrupt Window'],
    8: ['NMI window'],
    9: ['Task Switch'],
    10: ['CPUID'],
    11: ['GETSEC'],
    12: ['HLT', assigned_color()],     #
    13: ['INVD'],
    14: ['INVLPG'],
    15: ['RDPMC'],
    16: ['RDTSC'],
    17: ['RSM'],
    18: ['VMCALL'],
    19: ['VMCLEAR'],
    20: ['VMLAUNCH'],
    21: ['VMPTRLD'],
    22: ['VMPTRST'],
    23: ['VMREAD'],
    24: ['VMRESUME'],
    25: ['VMWRITE'],
    26: ['VMXOFF'],
    27: ['VMXON'],
    28: ['CR Access', assigned_color()],        #
    29: ['MOV DR'],
    30: ['I/O Instruction'],
    31: ['RDMSR'],
    32: ['WRMSR', assigned_color()],            #
    33: ['VM Entry Failure (invalid guest state)'],
    34: ['VM Entry Failure (MSR loading)'],
    35: ['n/a 35'],
    36: ['MWAIT'],
    37: ['Monitor trap flag'],
    38: ['n/a 38'],
    39: ['MONITOR'],
    40: ['PAUSE'],
    41: ['VM Entry Failure (machine check)'],
    42: ['n/a 42'],
    43: ['TPR below threshold'],
    44: ['APIC Access', assigned_color()],       #
    45: ['n/a 45'],
    46: ['Access to GDTR or IDTR'],
    47: ['Access to LDTR or TR'],
    48: ['EPT violation', assigned_color()],     #
    49: ['EPT misconfiguration'],
    50: ['INVEPT'],
    51: ['RDTSCP'],
    52: ['VMX preemption timer expired'],
    53: ['INVVPID'],
    54: ['WBINVD'],
    55: ['XSETBV'],
    56: ['APIC_WRITE', assigned_color()]         #
}

def convert_exit_df(df, label):
    # fill in the error reason text from the code in
    df.next_comm = df.next_comm.apply(lambda x: '(%02d) %s' % (x, KVM_EXIT_REASONS[x][0]))
    series_percent = df.next_comm.value_counts(normalize=True)
    series_count = df.next_comm.value_counts()
    series_percent = pandas.Series(["{0:.2f}%".format(val * 100) for val in series_percent],
                                   index=series_percent.index)

    series_percent.name = '%'
    series_count.name = label + ' count'

    res = pandas.concat([series_count, series_percent], axis=1)
    return res

def aggregate_dfs(dfds, task_re):
    '''
    Aggregate dfs from multiple cdicts into 1 df that has the task names
    sufficed with the cdict name
    :param dfds: a list of df desc
    :param task_re: regex for task names
    :return: a tuple made of
        an aggregated df with annotated task names
        a dict of multipliers indexed by the annotated task name, corresponding to the
               ratio between the requested cap time and the cdict cap time (always >= 1.0)
               that should be used to adjust counts
    '''
    adjust_count_ratios = {}
    # annotate the task name with the cdict ID it comes from
    dfl = []
    for dfd in dfds:
        df = dfd.df
        df = df[df['event'] == 'kvm_exit']
        df = df[df['task_name'].str.match(task_re)]
        # add the cdict name to the task name unless there is only 1 cdict file
        if len(dfds) > 1:
            df['task_name'] = df['task_name'].astype(str) + '.' + dfd.short_name
        # check the time span
        if dfd.multiplier >= 1.01:
            print
            print 'Warning: counts for %s will be multiplied by %f' % \
                  (dfd.name, dfd.multiplier)
            # all these task names require a count adjustment
            adjust_task_names = pandas.unique(df.task_name.ravel()).tolist()
            for atn in adjust_task_names:
                adjust_count_ratios[atn] = dfd.multiplier
        dfl.append(df)
    df = pandas.concat(dfl)
    return df, adjust_count_ratios

def get_exit_color(code):
    exit_desc = KVM_EXIT_REASONS[code]
    try:
        color = exit_desc[1]
    except IndexError:
        # unassigned color, assign one at runtime from a default color palette map
        color = str(next(default_color_palette))
        exit_desc.append(color)
    return color

'''
# Show aggregated time inside VM and inside KVM
print
print 'Aggregated duration:'
for event in legend_map:
    percent = accumulated_time[event] * 100 / total_time
    print '   %40s: %9d usec %3d%%' % (legend_map[event][1], accumulated_time[event], percent)
print '   %40s: %9d usec %3d%%' % ('Total', total_time, 100)
print

# all exit types
dfexits = df[df.event == 'kvm_exit']

# now keep only the last exit before a switch
# only keep kvm_exits and context switches
df = df[(df['event'] == 'kvm_exit') | (df['event'] == 'sched__sched_switch')]

# move all rows up
sdf = df.shift(-1)
# only keep rows that have a different event than their next row
df = df[df['event'] != sdf['event']]
# delete last row
df = df.drop(df.tail(1).index)

# delete all sched switches as they have served their purpose
df = df[df['event'] == 'kvm_exit']

show_exit_type_count(dfexits, df)

def show_exit_type_count(df_all_exits, df_last_exits):

    res_all = convert_exit_df(df_all_exits, 'total')
    res_last = convert_exit_df(df_last_exits, 'last exit')
    res = pandas.concat([res_all, res_last], axis=1)
    res.fillna(0, inplace=True)
    res.sort_values('total count', inplace=True, ascending=False)
    print res
'''
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
            cml.append({"task": task,  "counts": counts})

        coremap = {"run": dfd.short_name, "coremap":cml, "extent": str([min_count, max_count])}
        coremaps.append(coremap)
    return coremaps


def show_kvm_exit_types(dfds, cap_time_usec, task_re, label):

    # calculate the total cpu and total context switches per task
    cpu_sw_map = get_cpu_sw_map(dfds, cap_time_usec, task_re)

    coremaps = get_coremaps(dfds, cap_time_usec, task_re)

    # a dict of adjustment ratios indexed by task name for cdicts
    # that require count adjustment due to
    # capture window being too small
    df, adjust_count_ratios = aggregate_dfs(dfds, task_re)
    if df.empty:
        print 'Error: No kvm traces matching ' + task_re
        return

    df.drop(['cpu', 'duration', 'event', 'next_pid', 'pid', 'usecs'], inplace=True, axis=1)

    # Get the list of exit reason codes, sorted numerically
    exit_code_list = pandas.unique(df.next_comm.ravel()).tolist()
    exit_code_list.sort()

    # key = exit code, value = exit index
    exit_index_map = {}
    # index is the exit index
    exit_reason_list = []
    #     colormap_list = [
    #    {"exit":"EPT violation", "code":"#b2df8a"},
    #    {"exit":"VMRESUME", "code":"#b2df8a"},
    #    {"exit":"HLT", "code":"#b2df8a"}]
    colormap_list = []
    exit_index = 0
    for exit_code in exit_code_list:
        try:
            exit_reason_list.append(KVM_EXIT_REASONS[exit_code][0])
            colormap_list.append(get_exit_color(exit_code))
            exit_index_map[exit_code] = exit_index
            exit_index += 1
        except KeyError:
            # one of the next_comm row has an un-mapped exit reason code
            # bacause our map key range is contiguous, it must be a value out of range
            print 'Error: KVM exit reason %d unknown' % (exit_code)
            return

    # group by task name then exit reasons
    gb = df.groupby(['task_name', 'next_comm'])
    # number of exit types in each group
    # result is a series with 2-level index (task_name, next_comm)
    size_series = gb.size()

    # Get the list of all level 0 indices
    task_names = size_series.index.levels[0]

    #     task_list = [
    #    {"name":"Router", "exit_list":[{"name":"EPT violation", "count":400}, {"name":"APIC_WRITE", "count":300}]},
    #    {"name":"Firewall", "exit_list":[{"name":"VMRESUME", "count":300}, {"name":"HLT", "count":930}]}]
    task_list = []
    for task_name in task_names:
        exit_count_list = [0] * len(exit_reason_list)
        if adjust_count_ratios:
            try:
                multiplier = adjust_count_ratios[task_name]
            except KeyError:
                multiplier = 1
        else:
            multiplier = 1
        for exit_code, count in size_series[task_name].iteritems():
            exit_index = exit_index_map[exit_code]
            adj_count = int(count * multiplier)
            exit_count_list[exit_index] = adj_count
        # add the total to the count list
        try:
            cpu, sw = cpu_sw_map[task_name]
        except KeyError:
            # this task has no context switch no cpu, so likely is
            # using up all the cpu
            print 'keyerror:'+task_name
            cpu = 100
            sw = 1
        task_list.append({'name': task_name,
                         'exit_count': str(exit_count_list),
                         'cpu': round(cpu, 1),
                         'sw': sw})

    # get in reverse order so we display them top to bottom on a
    # horizontal stacked bar chart
    task_list.reverse()
    # Other misc information in the chart
    info = {
        "label": label,
        "window": "{:,d}".format(cap_time_usec / 1000),
        "date": time.strftime("%d-%b-%Y"),    # 01-Jan-2016 format
        "max_cores": 32,
        "version": __version__
    }
    template_loader = FileSystemLoader(searchpath=".")
    template_env = Environment(loader=template_loader, trim_blocks=True, lstrip_blocks=True)
    tpl = template_env.get_template("perfmap_kvm_exit_types.jinja")
    svg_html = tpl.render(exit_reason_list=str(exit_reason_list),
                          task_list=task_list,
                          colormap_list=str(colormap_list),
                          coremaps=coremaps,
                          info=info)
    output_svg_html(svg_html, 'kvm-types', task_re)
