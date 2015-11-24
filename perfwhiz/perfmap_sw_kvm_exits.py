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

import sys

from bokeh.plotting import figure, show
from bokeh.models.sources import ColumnDataSource
from bokeh.models import Range1d
from bokeh.io import gridplot

from perfmap_common import title_style
from perfmap_common import grid_title_style
from perfmap_common import output_html
from perfmap_common import get_disc_size

GREEN = "#5ab738"
RED = "#f22c40"
BLUE = "#4169E1"
ORANGE = "#FFA500"

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

def show_sw_kvm_heatmap(df, task_re, label, show_ctx_switches, show_kvm):
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
        prefix = 'swkvm'
    elif show_kvm:
        legend_map = legend_map_kvm
        title = "KVM events"
        prefix = 'kvm'
    else:
        legend_map = legend_map_ctx_sw
        title = "Scheduler events"
        prefix = 'sw'
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
    duration_max = usecs_max = -1
    duration_min = usecs_min = sys.maxint
    event_list = legend_map.keys()
    event_list.sort()

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

        for event in event_list:
            dfe = dfg[dfg.event == event]
            duration_min = min(duration_min, dfe['duration'].min())
            duration_max = max(duration_max, dfe['duration'].max())
            usecs_min = min(usecs_min, dfe['usecs'].min())
            usecs_max = max(usecs_max, dfe['usecs'].max())
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

    shared_x_range = Range1d(usecs_min, usecs_max)
    shared_y_range = Range1d(duration_min, duration_max)

    for p in chart_list:
        p.x_range = shared_x_range
        p.y_range = shared_y_range

    # specify how to output the plot(s)
    output_html(prefix, task_re)

    # display the figure
    if len(chart_list) == 1:
        show(chart_list[0])
    else:
        # split the list into an array of rows with 2 charts per row
        gp = gridplot(split_list(chart_list, 2))
        show(gp)
