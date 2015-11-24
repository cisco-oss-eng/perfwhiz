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
import itertools
import pandas
from pandas import DataFrame
import numpy as np

from bokeh.plotting import figure, show
from bokeh.models.sources import ColumnDataSource
from bokeh.models import HoverTool
from bokeh.palettes import Spectral6
from bokeh.palettes import YlOrRd9

from perfmap_common import title_style
from perfmap_common import output_html
from perfmap_common import get_time_span_msec
from perfmap_common import get_disc_size

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

GRAY = "#b5cbc5"

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
    df = df.drop('next_pid', axis=1)
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
