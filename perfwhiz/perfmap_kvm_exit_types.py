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

from perfmap_core import get_cpu_sw_map

import itertools
import numpy as np

# This palette is extracted from colorbrewer2 qualitative palette #2 with 12 colors
default_palette = ['#8dd3c7', '#ffffb3', '#bebada', '#fb8072', '#80b1d3', '#fdb462',
                   '#b3de69', '#fccde5', '#d9d9d9', '#bc80bd', '#ccebc5', '#ffed6f']
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

def update_task_list(task_list, cpu_sw_map):
    # Add stats for those tasks that do not have any KVM exits
    for task_name in cpu_sw_map:
        cpu, sw = cpu_sw_map[task_name]
        task_list.append({'name': task_name,
                          'exit_count': [],
                          'cpu': round(cpu, 1),
                          'sw': int(sw)})
    # get in reverse order so we display them top to bottom on a
    # horizontal stacked bar chart
    return sorted(task_list, key=lambda k: k['name'], reverse=True) 

def get_swkvm_data(dfds, cap_time_usec, task_re):
    task_list = []

    # calculate the total cpu and total context switches per task
    cpu_sw_map = get_cpu_sw_map(dfds, cap_time_usec, task_re)

    # a dict of adjustment ratios indexed by task name for cdicts
    # that require count adjustment due to
    # capture window being too small
    df, adjust_count_ratios = aggregate_dfs(dfds, task_re)
    if df.empty:
        print 'Warning: No kvm traces matching ' + task_re
        task_list = update_task_list(task_list, cpu_sw_map)
        # sort by task name
        return (task_list, [], [])
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
            cpu_sw_map.pop(task_name)
        except KeyError:
            # this task has no context switch no cpu, so likely is
            # using up all the cpu
            cpu = 100
            sw = 1
        task_list.append({'name': task_name,
                          'exit_count': str(exit_count_list),
                          'cpu': round(cpu, 1),
                          'sw': int(sw)})
    # Add stats for those tasks that do not have any KVM exits
    task_list = update_task_list(task_list, cpu_sw_map)

    return (task_list, exit_reason_list, colormap_list)
