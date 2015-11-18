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


from collections import OrderedDict
from optparse import OptionParser
import csv
import os
import sys
import itertools

import marshal
try:
    # try to use the faster version if available
    from msgpack import packb
    from msgpack import unpackb
except ImportError:
    # else fall back to the pure python version (slower)
    from umsgpack import packb
    from umsgpack import unpackb

import zlib
import pandas
from pandas import DataFrame
from pandas import Series
import numpy as np

from bokeh.plotting import figure, output_file, show
from bokeh.models.sources import ColumnDataSource
from bokeh.models import HoverTool
from bokeh.palettes import Spectral6
from bokeh.io import gridplot
from bokeh.charts import Bar
from bokeh.palettes import YlOrRd9

# Global variables

# start analysis after first from_time usec
from_time = 0
# cap input file to first cap_time usec, 0 = unlimited
cap_time = 0

# Standard title attribute for all figures
title_style = {'title_text_font_size': '12pt',
               'title_text_font_style': 'bold'}

grid_title_style = {'title_text_font_size': '10pt',
                    'title_text_font_style': 'bold'}

# calculate the time between the 1st entry and the last entry in msec
def get_time_span_msec(df):
    min_usec = df['usecs'].min()
    max_usec = df['usecs'].max()
    return (max_usec - min_usec) / 1000

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

# KVM exit reasons
# Intel64 and IA32 Architecture Software Developer's Manual Vol 3B, System Programming Guide Part 2
# Appendix I
KVM_EXIT_REASONS = [
    'Exception or NMI',     # 0
    'External Interrupt',
    'Triple Fault',
    'INIT',
    'Startup IPI',
    'I/O SMI (System Management Interrupt)',
    'Other SMI',
    'Interrupt Window',
    'NMI window',
    'Task Switch',
    'CPUID',                # 10
    'GETSEC',
    'HLT',                  # 12
    'INVD',
    'INVLPG',
    'RDPMC',
    'RDTSC',
    'RSM',
    'VMCALL',
    'VMCLEAR',
    'VMLAUNCH',             # 20
    'VMPTRLD',
    'VMPTRST',
    'VMREAD',
    'VMRESUME',
    'VMWRITE',
    'VMXOFF',
    'VMXON',
    'Control Register Access',
    'MOV DR',
    'I/O Instruction',      # 30
    'RDMSR',
    'WRMSR',
    'VM Entry Failure (invalid guest state)',
    'VM Entry Failure (MSR loading)',
    'n/a 35',
    'MWAIT',
    'Monitor trap flag',
    'n/a 38',
    'MONITOR',
    'PAUSE',                # 40
    'VM Entry Failure (machine check)',
    'n/a 42',
    'TPR below threshold',
    'APIC Access',
    'n/a 45',
    'Access to GDTR or IDTR',
    'Access to LDTR or TR',
    'EPT violation',
    'EPT misconfiguration',
    'INVEPT',               # 50
    'RDTSCP',
    'VMX preemption timer expired',  # 52
    'INVVPID',
    'WBINVD',
    'XSETBV'
]
GREEN = "#5ab738"
RED = "#f22c40"
BLUE = "#4169E1"
YELLOW = "#FFFF00"
ORANGE = "#FFA500"
GRAY = "#b5cbc5"
WHITE = "#ffffff"

def cycle_colors(chunk, palette=Spectral6):
    """ Build a color list just cycling through a given palette.

    Args:
        chuck (seq): the chunk of elements to generate the color list
        palette (seq[color]) : a palette of colors to cycle through

    Returns:
        colors

    """
    colors = []

    g = itertools.cycle(palette)
    for i in range(len(chunk)):
        colors.append(next(g))

    return colors

def get_disc_size(count):
    if count < 100:
        return 10
    if count < 500:
        return 8
    return 6

def output_html(chart_type, task_re):
    filename = html_file + '_' + chart_type + '_' + task_re + '.html'
    output_file(filename)
    print('Saved to ' + filename)

def get_full_task_name(df, task):
    # if task is a number it is considered to be a pid ID
    # if text it is a task name
    try:
        tid = int(task)
        # tid given
        df = df[df['pid'] == tid]
        task = None
        # get the task name from the tid
    except ValueError:
        # task given: find corresponding tid
        df = df[df['task_name'] == task]
        tid = 0

    if df.empty:
        print 'No selection matching the task ' + task
        return (None, None)
    # fill in the missing information
    if not tid:
        tid = df['pid'].iloc[0]
    if not task:
        task = df['task_name'].iloc[0]
    task = task + ':' + str(tid)
    return (df, task)

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

def split_list(l, n):
    # split a list into multiple lists of given len
    n = max(1, n)
    return [l[i:i + n] for i in range(0, len(l), n)]

def show_sw_heatmap(df, task_re, label, show_ctx_switches, show_kvm):
    gb = get_groupby(df, task_re)

    chart_list = []
    # these are the 2 main events to show for kvm events
    legend_map_kvm = {
        'kvm_exit': (BLUE, 'vcpu running (y=vcpu run time)', False),
        'kvm_entry': (ORANGE, 'vcpu not running (y=kvm+sleep time)', False)
    }
    # context switch events
    legend_map_ctx_sw = {
        'sched__sched_stat_sleep': (RED, 'wakeup from sleep (y=sleep time)', True),
        'sched__sched_switch': (GREEN, 'switched out from cpu (y=run time)', True)
    }
    if show_kvm and show_ctx_switches:
        legend_map = dict(legend_map_kvm.items() + legend_map_ctx_sw.items())
        title = "Scheduler and KVM events"
    elif show_kvm:
        legend_map = legend_map_kvm
        title = "KVM events"
    else:
        legend_map = legend_map_ctx_sw
        title = "Scheduler events"
    width = 1000
    height = 800
    show_legend = True
    nb_charts = len(gb.groups)
    if nb_charts == 0:
        print 'No selection matching: ' + task_re
        return
    if nb_charts > 1:
        width /= 2
        height /= 2
        tstyle = grid_title_style
    else:
        tstyle = title_style
    task_list = gb.groups.keys()
    task_list.sort()
    show_legend = True

    for task in task_list:
        p = figure(plot_width=width, plot_height=height, y_axis_type="log", **tstyle)
        p.xaxis.axis_label = 'time (usecs)'
        p.yaxis.axis_label = 'duration (usecs)'
        p.legend.orientation = "bottom_right"
        p.xaxis.axis_label_text_font_size = "10pt"
        p.yaxis.axis_label_text_font_size = "10pt"
        if label:
            p.title = "%s for %s (%s)" % (title, task, label)
            label = None
        else:
            p.title = task
        p.ygrid.minor_grid_line_color = 'navy'
        p.ygrid.minor_grid_line_alpha = 0.1
        accumulated_time = {}
        total_time = 0
        dfg = gb.get_group(task)
        # remove any row with zero duration as it confuses the chart library
        dfg = dfg[dfg['duration'] > 0]
        event_list = legend_map.keys()
        event_list.sort()
        for event in event_list:
            dfe = dfg[dfg.event == event]
            count = len(dfe)
            color, legend_text, cx_sw = legend_map[event]
            if show_legend:
                legend_text = '%s (%d)' % (legend_text, count)
            elif color == GREEN:
                legend_text = '(%d)' % (count)
            else:
                legend_text = None
            # there is bug in bokeh when there are too many circles to draw, nothing is visible
            if len(dfe) > 50000:
                dfe = dfe[:50000]
                print 'Series for %s display truncated to 50000 events' % (event)
            if cx_sw:
                draw_shape = p.circle
                size = get_disc_size(count)
            else:
                draw_shape = p.diamond
                size = get_disc_size(count) + 4

            draw_shape('usecs', 'duration', source=ColumnDataSource(dfe),
                       size=size,
                       color=color,
                       alpha=0.3,
                       legend=legend_text)
            event_duration = dfe['duration'].sum()
            accumulated_time[event] = event_duration
            total_time += event_duration
        chart_list.append(p)
        show_legend = False

    # specify how to output the plot(s)
    output_html('kvm', task_re)

    # display the figure
    if len(chart_list) == 1:
        show(chart_list[0])
    else:
        # split the list into an array of rows with 2 charts per row
        gp = gridplot(split_list(chart_list, 2))
        show(gp)

def get_color(percent, palette):
    try:
        percent = int(percent)
    except ValueError:
        # swapper tasks always have NaN since their duration is always 0
        percent = 100
    if percent >= 100:
        return palette[-1]
    return palette[percent * len(palette) // 100]

def get_color_value_list(min_count, max_count, palette, range_unit):
    value_list = []
    color_count = len(palette)
    increment = float(max_count - min_count) / color_count
    value_list = np.arange(min_count, max_count + 1, increment).astype(np.int).astype(str).tolist()
    if range_unit:
        value_list = [x + range_unit for x in value_list]
    return value_list

def show_core_runs(df, task_re, label, duration):
    time_span_msec = get_time_span_msec(df)

    # remove unneeded columns
    df.drop('next_pid', axis=1, inplace=True)
    df.drop('pid', axis=1, inplace=True)
    df.drop('usecs', axis=1, inplace=True)
    df.drop('next_comm', axis=1, inplace=True)

    # filter out all events except the switch events
    df = df[df.event == 'sched__sched_switch']
    df = df.drop('event', axis=1)
    df = df[df['task_name'].str.match(task_re)]

    # at this point we have a df that looks like this:
    #         task_name  cpu  duration
    # 0     ASA.1.vcpu0    8      7954
    # 1     ASA.1.vcpu0    9      5475
    # 2     ASA.1.vcpu0   10      4151
    # 3     ASA.1.vcpu0   11     12391
    # 4     ASA.1.vcpu0   12     21025
    # 5     ASA.1.vcpu0   13      6447
    # 6     ASA.1.vcpu0   14     16798
    # 7     ASA.1.vcpu0   15      3911
    # 8    ASA.10.vcpu0    8      4248
    # 9    ASA.10.vcpu0    9      3534
    # 10   ASA.10.vcpu0   10     15624
    # 11   ASA.10.vcpu0   11      6925
    # etc...
    if len(df) == 0:
        print
        print 'No selection matching "%s"' % (task_re)
        return
    gb = df.groupby(['task_name', 'cpu'], as_index=False)
    if duration:
        # add duration values
        df = gb.aggregate(np.sum)
        max_core = df.cpu.max()

        dfsum = df.drop('cpu', axis=1)
        gb = dfsum.groupby('task_name', as_index=False)
        dfsum = gb.aggregate(np.sum)
        # dfsum is the sum of all duration for given task
        # 0    ASA.1.vcpu0     78152
        # 1   ASA.10.vcpu0     65637
        # 2   ASA.11.vcpu0     81525
        # 3   ASA.12.vcpu0     56488
        # For each task, the maximum runtime is the time_span_msec (100% of 1 core)
        # The idle time for each task is therefore time_span_msec * 1000 - sum(duration)
        dfsum['cpu'] = 'IDLE'
        time_span_usec = time_span_msec * 1000
        dfsum['duration'] = time_span_usec - dfsum['duration']

        # now we need to reinsert that data back to the df
        dfm = pandas.concat([df, dfsum], ignore_index=True)

        #         task_name  cpu  duration  total
        # 0     ASA.1.vcpu0    8      7954  78152
        # 1     ASA.1.vcpu0    9      5475  78152
        # 2     ASA.1.vcpu0   10      4151  78152

        # Add a % column
        dfm['percent'] = ((dfm['duration'] * 100 * 10) // time_span_usec) / 10

        # This is for the legend
        min_count = 0
        max_count = 100
        range_unit = '%'

        # many core-pinned system tasks have a duration of 0 (swapper, watchdog...)
        dfm.fillna(100, inplace=True)
        dfm.drop(['duration'], axis=1, inplace=True)
        tooltip_count = ("time", "@percent% of core @cpu")
        title = "Task Run Time %% per Core (%s, %d msec window)" % (label, time_span_msec)
        # this is YlGnBu9[::-1]  (Reverse the color order so dark is highest value)
        # with an extra intermediate color to make it 10
        palette = ['#ffffd9', '#edf8b1', '#c7e9b4', '#a3dbb7', '#7fcdbb',
                   '#41b6c4', '#1d91c0', '#225ea8', '#253494', '#081d58']
        html_prefix = 'core_runtime'
        # add 1 extra column in the heatmap for core "IDLE" to represent the IDLE time
        # this requires adding 1 row per real core that has a runtime set to
        # capture window size - sum(duration on all cores)
    else:
        # count number of rows with same task and cpu
        dfm = DataFrame(gb.size())
        dfm.reset_index(inplace=True)
        dfm.rename(columns={0: 'count'}, inplace=True)
        min_count = dfm['count'].min()
        max_count = dfm['count'].max()
        range_unit = ''
        spread = max_count - min_count
        # Add a % column
        dfm['percent'] = ((dfm['count'] - min_count) * 100) / spread
        tooltip_count = ("context switches", "@count")
        title = "Task Context Switches per Core (%s, %d msec window)" % (label, time_span_msec)
        palette = YlOrRd9[::-1]
        html_prefix = 'core_switches'
        max_core = dfm.cpu.max()

    # get the list of cores
    # round up to next mutliple of 4 - 1
    # 0..3 -> 3
    # 4..7 -> 7 etc
    max_core |= 0x03
    max_core = max(max_core, 3)
    core_list = [str(x) for x in range(max_core + 1)]
    if duration:
        core_list.append('IDLE')
    # make room for the legend by adding 3 empty columns
    core_list += ['', '', '']
    dfm['cpu'] = dfm['cpu'].astype(str)
    # replace ':' with '_' as it would cause bokeh to misplace the labels on the chart
    dfm['task_name'] = dfm['task_name'].str.replace(':', '_')

    normalize_df_task_name(dfm)

    # Add a column for the Y axis
    # each task name should be associated to a unique Y index
    # Get a unique list of task names sorted
    task_list = pandas.unique(dfm.task_name.ravel()).tolist()
    task_list.sort()

    # Add a color column
    dfm['color'] = dfm.apply(lambda row: get_color(row['percent'],
                                                   palette), axis=1)
    # switch to str type to prevent the tooltip to
    # display percent value with 3 digits
    dfm.percent = dfm.percent.astype(str)
    # make enough vertical space for the legend
    # the legend needs 1 row per palette color + 1 to fit the max value
    # so we need at least len(palette) + 1 rows
    if len(task_list) < len(palette) + 1:
        task_list += ['' for _ in range(len(palette) + 1 - len(task_list))]
    TOOLS = "resize,hover,save"
    p = figure(title=title, tools=TOOLS, x_range=core_list, y_range=task_list, **title_style)

    p.plot_width = 1000
    p.plot_height = 80 + len(task_list) * 16
    p.toolbar_location = "left"
    source = ColumnDataSource(dfm)
    # the name is to flag these rectangles to enable tooltip hover on them
    # (and not enable tooltips on the legend patches)
    p.rect("cpu", "task_name", width=1, height=0.9, source=source, fill_alpha=0.8, color="color", name='patches')
    p.grid.grid_line_color = None
    # trace separator lines to isolate blocks across core groups (numa sockets) and task-like names
    max_y = len(task_list)
    # trace a vertical line every 8 cores
    for seg_x in range(8, max_core + 7, 8):
        p.segment(x0=[seg_x + 0.5], y0=[0], x1=[seg_x + 0.5],
                  y1=[max_y + 0.5], color=GRAY, line_width=2)
    prev_task_name = None
    # trace a horizontal line around every group of tasks that have the same first 3 characters
    for y in range(max_y):
        cur_task_name = task_list[y]
        if prev_task_name:
            if prev_task_name[0:3] != cur_task_name[0:3]:
                p.segment(x0=[0], y0=[y + 0.5], x1=[max_core + 1.5],
                          y1=[y + 0.5], color=GRAY, line_width=0.5)
        prev_task_name = task_list[y]

    hover = p.select(dict(type=HoverTool))
    hover.tooltips = OrderedDict([
        ("task", "@task_name"),
        ("core", "@cpu"),
        tooltip_count
    ])
    # only enable tooltip on rectangles with name 'patches'
    hover.names = ['patches']

    # legend to the right
    # we try to center the legend vertically
    legend_base_y = 0
    palette_len = len(palette)
    if max_y > palette_len + 1:
        legend_base_y = (max_y - palette_len - 1) // 2

    if duration:
        # IDLE cpu inserted so shift the legend by 1 position to the right
        max_core += 1
    # pass 1 is to draw the color patches
    # prepare a data source with a x, y and a color column
    x_values = np.empty(palette_len)
    x_values.fill(max_core + 2.5)
    y_values = np.arange(legend_base_y + 1.5, legend_base_y + palette_len + 1, 1)
    dfl = DataFrame({'x': x_values, 'y': y_values, 'color': palette})
    source = ColumnDataSource(dfl)
    p.rect(x='x', y='y', color='color', width=1, height=1, source=source)

    # pass 2 is to draw the text describing the ranges for the color patches
    color_value_list = get_color_value_list(min_count, max_count, palette, range_unit)
    x_values = np.empty(len(color_value_list))
    x_values.fill(max_core + 3.1)
    y_values = np.arange(legend_base_y + 0.7, legend_base_y + len(color_value_list), 1)

    dfl = DataFrame({'x': x_values, 'y': y_values, 'color_values': color_value_list})
    source = ColumnDataSource(dfl)
    p.text(x='x', y='y', text='color_values', source=source,
           text_font_size='8pt')

    output_html(html_prefix, task_re)
    show(p)

def convert_exit_df(df, label):
    # fill in the error reason text from the code in
    df.next_comm = df.next_comm.apply(lambda x: '(%02d) %s' % (x, KVM_EXIT_REASONS[x]))
    series_percent = df.next_comm.value_counts(normalize=True)
    series_count = df.next_comm.value_counts()
    series_percent = pandas.Series(["{0:.2f}%".format(val * 100) for val in series_percent],
                                   index=series_percent.index)

    series_percent.name = '%'
    series_count.name = label + ' count'

    res = pandas.concat([series_count, series_percent], axis=1)
    return res

def show_exit_type_count(df_all_exits, df_last_exits):

    res_all = convert_exit_df(df_all_exits, 'total')
    res_last = convert_exit_df(df_last_exits, 'last exit')
    res = pandas.concat([res_all, res_last], axis=1)
    res.fillna(0, inplace=True)
    res.sort_values('total count', inplace=True, ascending=False)
    print res

def show_kvm_exit_types(df, task_re, label):
    df = df[df['event'] == 'kvm_exit']
    df = df[df['task_name'].str.match(task_re)]
    # the next_comm column contains the exit code
    exit_codes = Series(KVM_EXIT_REASONS)
    # add  new column congaining the exit reason in clear text
    df['exit_reason'] = df['next_comm'].map(exit_codes)
    time_span_msec = get_time_span_msec(df)
    df.drop(['cpu', 'duration', 'event', 'next_pid', 'pid', 'next_comm', 'usecs'], inplace=True, axis=1)
    # group by task name then exit reasons
    gb = df.groupby(['task_name', 'exit_reason'])
    # number of exit types
    size_series = gb.size()
    df = size_series.to_frame('count')
    df.reset_index(inplace=True)

    p = Bar(df, label='task_name', values='count', stack='exit_reason',
            title="KVM Exit types per task (%s, %d msec window)" % (label, time_span_msec),
            legend='top_right',
            width=800, height=800)
    p._xaxis.axis_label = "Task Name"
    p._xaxis.axis_label_text_font_size = "12pt"
    p._yaxis.axis_label = "Exit Count (sum)"
    p._yaxis.axis_label_text_font_size = "12pt"
    # syecify how to output the plot(s)
    output_html('kvm-types', task_re)

    # display the figure
    show(p)

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
    '''

def show_core_locality(df, task_re, label):

    df = df[df['event'] == 'sched__sched_switch']
    df = df[df['task_name'].str.match(task_re)]
    # aggregate all the per core tasks (e.g. swapper/0 -> swapper)
    df['task_name'] = df['task_name'].str.replace(r'/.*$', '')
    # group by task name
    gb = df.groupby('task_name')
    task_list = gb.groups

    p = figure(plot_width=1000, plot_height=800, **title_style)

    p.xaxis.axis_label = 'time (usecs)'
    p.yaxis.axis_label = 'core'
    p.legend.orientation = "bottom_right"
    p.xaxis.axis_label_text_font_size = "10pt"
    p.yaxis.axis_label_text_font_size = "10pt"
    p.title = "Core locality (%s)" % (label)

    color_list = cycle_colors(task_list)

    for task, color in zip(task_list, color_list):
        dfe = gb.get_group(task)
        # add 1 column to contain the starting time for each run period
        dfe['start'] = dfe['usecs'] - dfe['duration']
        tid = dfe['pid'].iloc[0]
        count = len(dfe)
        legend_text = '%s:%d (%d)' % (task, tid, count)
        # draw end of runs
        p.circle('usecs', 'cpu', source=ColumnDataSource(dfe),
                 size=get_disc_size(count) + 2, color=color,
                 alpha=0.3,
                 legend=legend_text)
        # draw segments to show the entire runs
        p.segment('start', 'cpu', 'usecs', 'cpu', line_width=5, line_color=color,
                  source=ColumnDataSource(dfe))

    # specify how to output the plot(s)
    output_html('coreloc', task_re)

    # display the figure
    show(p)

def show_successors(df, task, label):
    df, task = get_full_task_name(df, task)
    if not task:
        return
    df = df[df['event'] == 'sched__sched_switch']
    # aggregate all the per core tasks (e.g. swapper/0 -> swapper)
    df['next_comm'] = df['next_comm'].str.replace(r'/.*$', '')
    series_percent = df.next_comm.value_counts(normalize=True)
    series_count = df.next_comm.value_counts()
    series_percent = pandas.Series(["{0:.2f}%".format(val * 100) for val in series_percent],
                                   index=series_percent.index)

    series_percent.name = 'percent'
    series_count.name = 'count'
    print 'Successors of %s (%s)' % (task, label)
    print pandas.concat([series_count, series_percent], axis=1)

def convert(df, new_cdict):
    # Convert the old style cdict (marshal based) to the new cdict format
    # The new format is msgpack based and fixes the runtime reporting bug
    # by aggregating all runtime durations into the next switch event
    # and removing the runtime events
    # A dict of runtime delays accumulated indexed by cpu
    runtime_by_cpu = {}
    # aggregate all runtimes per cpu
    count = len(df)
    print 'Conversion in progress...'
    for index in xrange(count):
        event_name = df['event'].iloc[index]
        cpu = df['cpu'].iloc[index]
        if event_name == 'sched__sched_stat_runtime':
            try:
                duration = df['duration'].iloc[index]
                runtime_by_cpu[cpu] += duration
            except KeyError:
                # the counter is set in on the first sched switch for each cpu
                pass
        elif event_name == 'sched__sched_switch':
            try:
                if df['pid'].iloc[index]:
                    # don't bother to update swapper (pid=0)
                    runtime = runtime_by_cpu[cpu]
                    df.set_value(index, 'duration', runtime)
            except KeyError:
                pass
            runtime_by_cpu[cpu] = 0
    # get rid of all the runtime events
    df = df[df['event'] != 'sched__sched_stat_runtime']
    print 'End of conversion, marshaling and compressing...'
    df.fillna(value=0, inplace=True, downcast='infer')
    # save new cdict
    with open(new_cdict, 'w') as ff:
        res = {'event': df['event'].tolist(),
               'cpu': df['cpu'].tolist(),
               'usecs': df['usecs'].tolist(),
               'pid': df['pid'].tolist(),
               'task_name': df['task_name'].tolist(),
               'duration': df['duration'].tolist(),
               'next_pid': df['next_pid'].tolist(),
               'next_comm': df['next_comm'].tolist()}
        compressed = zlib.compress(packb(res))
        ff.write(compressed)
        print 'Compressed dictionary written to %s %d entries size=%d bytes' % \
              (new_cdict, len(df), len(compressed))

def remap(perf_dict, csv_map):
    # a mapping dict of task names indexed by the tid
    map_dict = {}
    print 'Remapping task names...'
    with open(csv_map, 'r') as ff:
        # 19236,instance-000019f4,emulator,8f81e3a1-3ebd-4015-bbee-e291f0672d02,FULL,5,CSR
        reader = csv.DictReader(ff, fieldnames=['tid', 'libvirt_id', 'thread_type', 'uuid', 'chain_type',
                                                'chain_id', 'nvf_name'])
        for row in reader:
            task_name = '%s.%02d.%s' % (row['nvf_name'], int(row['chain_id']), row['thread_type'])
            map_dict[int(row['tid'])] = task_name
    pids = perf_dict['pid']
    names = perf_dict['task_name']
    next_pids = perf_dict['next_pid']
    next_comms = perf_dict['next_comm']
    count = 0
    for index in xrange(len(pids)):
        try:
            new_task_name = map_dict[pids[index]]
            names[index] = new_task_name
            count += 1
        except KeyError:
            pass
        try:
            new_task_name = map_dict[next_pids[index]]
            next_comms[index] = new_task_name
            count += 1
        except KeyError:
            pass
    print 'Remapped %d task names' % (count)

# ---------------------------------- MAIN -----------------------------------------

parser = OptionParser(usage="usage: %prog [options] <cdict_file>")


parser.add_option("--successors-of",
                  dest="successor_of_task",
                  help="show list of successors of given tid or task name"
                  )
parser.add_option("--show-tids",
                  dest="show_tids",
                  action="store_true",
                  default=False,
                  help="show list of all tids with event count)"
                  )
parser.add_option("--core-locality",
                  dest="core_loc",
                  action="store",
                  metavar="task name (regex)",
                  help="show core locality heat map for tasks with matching name"
                  )
parser.add_option("--core-runtime",
                  dest="core_runtime",
                  action="store",
                  metavar="task name (regex)",
                  help="show % runtime on each core for selected tasks"
                  )
parser.add_option("--core-switch-count",
                  dest="core_switches",
                  action="store",
                  metavar="task name (regex)",
                  help="show context switch count on each core for selected tasks"
                  )
parser.add_option("-t", "--task",
                  dest="task",
                  metavar="task name (regex)",
                  help="show thread context switch heat map (use numeric tid or task name regex)"
                  )
parser.add_option("--kvm-exits",
                  dest="kvm_exits",
                  metavar="task name (regex)",
                  help="show thread kvm exits heat map"
                  )
parser.add_option("--tk",
                  dest="tk",
                  metavar="task name (regex)",
                  help="show thread context switches and kvm exits heat map"
                  )
parser.add_option("--kvm-exit-types",
                  dest="kvm_exit_types",
                  metavar="task name (regex)",
                  help="show thread kvm exit types bar charts"
                  )
parser.add_option("--label",
                  dest="label",
                  metavar="label",
                  help="label for the title (defaulst to the cdict file name)"
                  )
parser.add_option("-c", "--cap",
                  dest="cap_time",
                  help="(optional) cap the analysis to first <cap_time> msec"
                       " of capture (default=all)"
                  )
parser.add_option("-f", "--from",
                  dest="from_time",
                  help="(optional) start the analysis after first <from_time> msec"
                       " of capture (default=0)"
                  )
parser.add_option("--map",
                  dest="map",
                  action="store",
                  metavar="mapping csv file",
                  help="remap task names from mapping csv file"
                  )
parser.add_option("--convert",
                  dest="convert",
                  action="store",
                  metavar="new cdict file",
                  help="(Deprecated) migrate to new encoding with runtime aggregation into switch"
                  )
(options, args) = parser.parse_args()

if options.from_time:
    from_time = int(options.from_time) * 1000
if options.cap_time:
    # convert to usec
    cap_time = int(options.cap_time) * 1000 + from_time

if not args:
    print 'Missing cdict file'
    sys.exit(1)

cdict_file = args[0]
if not cdict_file.endswith('.cdict'):
    # automatically add the cdict extension if there is one
    if os.path.isfile(cdict_file + '.cdict'):
        cdict_file += '.cdict'
    else:
        print('input file name must have the .cdict extension')

with open(cdict_file, 'r') as ff:
    cdict = ff.read()

decomp = zlib.decompress(cdict)
try:
    perf_dict = unpackb(decomp)
except Exception:
    # old serialization format
    perf_dict = marshal.loads(decomp)

if options.map:
    remap(perf_dict, options.map)

df = DataFrame(perf_dict)
html_file = cdict_file.replace('.cdict', '')

# filter on usecs
if from_time:
    df = df[df['usecs'] >= from_time]
if cap_time:
    df = df[df['usecs'] <= cap_time]


if not options.label:
    options.label = os.path.splitext(os.path.basename(cdict_file))[0]

if options.show_tids:
    res = df.groupby(['pid', 'task_name']).size()
    res.sort_values(ascending=False, inplace=True)
    print 'List of tids and task names sorted by context switches and kvm event count'
    print res
elif options.core_loc:
    show_core_locality(df, options.core_loc, options.label)
elif options.task:
    show_sw_heatmap(df, options.task, options.label, True, False)
elif options.kvm_exits:
    show_sw_heatmap(df, options.kvm_exits, options.label, False, True)
elif options.tk:
    show_sw_heatmap(df, options.tk, options.label, True, True)
elif options.kvm_exit_types:
    show_kvm_exit_types(df, options.kvm_exit_types, options.label)
elif options.successor_of_task:
    show_successors(df, options.successor_of_task, options.label)
elif options.convert:
    convert(df, options.convert)


if options.core_runtime:
    show_core_runs(df, options.core_runtime, options.label, True)
if options.core_switches:
    show_core_runs(df, options.core_switches, options.label, False)
