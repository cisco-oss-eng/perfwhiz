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


from optparse import OptionParser
import os
import sys
import warnings
import pandas
from pandas import DataFrame
import json
import traceback

from perf_formatter import open_cdict

from perfmap_common import set_html_file
from perfmap_common import DfDesc
from perfmap_common import output_svg_html
from perfmap_core import get_coremaps
from perfmap_kvm_exit_types import get_swkvm_data
from perfmap_sw_kvm_exits import get_sw_kvm_events

from jinja2 import Environment
from jinja2 import FileSystemLoader
import time
from __init__ import __version__
from pkg_resources import resource_filename
import zlib
import base64

# Global variables
output_chart = None

# start analysis after first from_time usec
from_time = 0
# cap input file to first cap_time usec, 0 = unlimited
cap_time = 0

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

def set_short_names(dfds):
    '''
    Reduce the names of a list of dataframe descriptors to minimal non matching characters
    This will basically trim from the start and end all common strings and keep only the
    non matching part of the names.
    Example of names: ../../haswell/h1x216.cdict    ../../haswell/h5x113.cdict
    Resulting reduced names: h1x216 h5x113
    Caveat: do not strip out any numeric digits at both ends, e.g. 01x218.cdict 02x208.cdict
    must return [1x218, 2x208] must not cut out the trailing 8

    '''
    name_list = [dfd.name for dfd in dfds]
    if len(name_list) < 2:
        return
    strip_head = None
    strip_tail = None
    for name in name_list:
        if not strip_head:
            strip_head = name
            strip_tail = name
            continue
        # because there are no duplicates we know that
        # at least 1 character difference between all keys
        # find longest match from head
        max_index = min(len(name), len(strip_head))
        for index in range(max_index):
            if name[index] != strip_head[index] or name[index].isdigit():
                strip_head = name[:index]
                break

        # find longest match from tail
        max_index = min(len(name), len(strip_tail))
        for index in range(-1, -max_index - 1, -1):
            # stop when mismatch or when hitting a numeric letter
            if name[index] != strip_tail[index] or name[index].isdigit():
                if index == -1:
                    strip_tail = ''
                else:
                    strip_tail = name[1 + index:]
                break

    # strip all names and store in the short_name field
    for dfd in dfds:
        dfd.short_name = dfd.name[len(strip_head):]
        if strip_tail:
            dfd.short_name = dfd.short_name[:-len(strip_tail)]

def get_info(dfd, label):
    # Other misc information in the chart
    return {
        "label": label,
        "window": "{:,d}".format((dfd.to_usec - dfd.from_usec) / 1000),
        "date": time.strftime("%d-%b-%Y"),    # 01-Jan-2016 format
        "max_cores": 32,
        "version": __version__
    }

def get_tpl(tpl_file):
    local_path = resource_filename(__name__, tpl_file)
    template_loader = FileSystemLoader(searchpath=os.path.dirname(local_path))
    template_env = Environment(loader=template_loader, trim_blocks=True, lstrip_blocks=True)
    return template_env.get_template(tpl_file)

def create_charts(dfds, cap_time_usec, task_re, label):
    coremaps = get_coremaps(dfds, cap_time_usec, task_re)
    task_list, exit_reason_list, colormap_list = get_swkvm_data(dfds, cap_time_usec, task_re)
    tpl = get_tpl('perfmap_charts.jinja')
    svg_html = tpl.render(exit_reason_list=str(exit_reason_list),
                          task_list=task_list,
                          colormap_list=str(colormap_list),
                          coremaps=coremaps,
                          info=get_info(dfds[0], label))
    output_svg_html(svg_html, 'charts', task_re)

def create_heatmaps(dfd, cap_time_usec, task_re, label):
    swk_events = get_sw_kvm_events(dfd, task_re)

    tpl = get_tpl('perfmap_heatmaps.jinja')
    json_swk = json.dumps(swk_events, separators=(',', ':'))
    b64_zlib = base64.b64encode(zlib.compress(json_swk))
    svg_html = tpl.render(swk_events=b64_zlib,
                          info=get_info(dfd, label))
    output_svg_html(svg_html, 'heatmaps', task_re)

# ---------------------------------- MAIN -----------------------------------------

def main():
    global from_time
    global cap_time

    # Suppress future warnings
    warnings.simplefilter(action='ignore', category=FutureWarning)

    parser = OptionParser(usage="usage: %prog [options] <cdict_file1> [cdict_file2...]")

    parser.add_option("-t", "--task",
                      dest="task",
                      metavar="task name (regex)",
                      help="selected task(s) (regex on task name)"
                      )
    parser.add_option("--label",
                      dest="label",
                      metavar="label",
                      help="label for the title (defaults to the cdict file name)"
                      )
    parser.add_option("--map",
                      dest="map",
                      action="store",
                      metavar="mapping csv file",
                      help="remap task names from mapping csv file"
                      )
    parser.add_option("--output-dir",
                      dest="output_dir",
                      action="store",
                      metavar="dir pathname",
                      help="output all html files to the provided directory"
                      )
    parser.add_option("--heatmaps",
                      dest="heatmaps",
                      action="store_true",
                      help="generate heatmap charts only (default: generate basic charts only)"
                      )
    parser.add_option("--headless",
                      dest="headless",
                      action="store_true",
                      help="do not show chart in the browser (default=False)"
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
    parser.add_option("--merge-sys-tasks",
                      dest="merge_sys_tasks",
                      action="store_true",
                      help="group all system tasks (e.g. swapper/0 -> swapper)"
                      )
    parser.add_option("--append-tid",
                      dest="append_tid",
                      action="store_true",
                      help="append tid to task name (e.g. perf -> perf:2834)"
                      )
    parser.add_option("--successors-of",
                      dest="successor_of_task",
                      help="only show list of successors of given tid or task name"
                      )
    parser.add_option("--list",
                      dest="list",
                      action="store_true",
                      default=False,
                      help="only show list of all tasks with event count"
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

    if options.output_dir:
        if not os.path.isdir(options.output_dir):
            print('Invalid output directory: ' + options.output_dir)
            sys.exit(1)

    dfds = []
    cdict_files = args
    if len(cdict_files):
        if len(cdict_files) > 1:
            html_filename = cdict_files[0] + '-diff'
        else:
            html_filename = cdict_files[0]
    else:
        html_filename = cdict_files[0] if len(cdict_files) else 'perfwhiz'
    set_html_file(html_filename, options.headless, options.label, options.output_dir)

    # get smallest capture window of all cdicts
    min_cap_usec = 0
    for cdict_file in cdict_files:
        perf_dict = open_cdict(cdict_file, options.map)
        df = DataFrame(perf_dict)
        dfd = DfDesc(cdict_file, df, options.merge_sys_tasks, options.append_tid)
        dfds.append(dfd)
        last_usec = df['usecs'].iloc[-1]
        if min_cap_usec == 0:
            min_cap_usec = last_usec
        else:
            min_cap_usec = min(min_cap_usec, last_usec)
    if from_time and from_time >= min_cap_usec:
        print 'Error: from time cannot be larger than %d msec' % (min_cap_usec / 1000)
        sys.exit(2)
    # if a cap time is provided, always use that value (even if it is >min_cap_usec)
    if not cap_time:
        cap_time = min_cap_usec

    # normalize all dataframes
    for dfd in dfds:
        dfd.normalize(from_time, cap_time)

    # at this point some cdict entries may have "missing" data
    # if the requested cap_time is > the cdict cap time
    # the relevant processing will extrapolate when needed (and if possible)

    # reduce all names to minimize the length o;f the cdict file name
    set_short_names(dfds)

    if not options.label:
        if len(dfds) > 1:
            options.label = 'diff'
        else:
            options.label = os.path.splitext(os.path.basename(cdict_file))[0]

    if options.list:
        print 'List of tids and task names sorted by context switches and kvm event count'
        for dfd in dfds:
            print dfd.name + ':'
            res = dfd.df.groupby(['pid', 'task_name']).size()
            res.sort_values(ascending=False, inplace=True)
            pandas.set_option('display.max_rows', len(res))
            print res
        sys.exit(0)

    if options.successor_of_task:
        for dfd in dfds:
            print dfd.name + ':'
            show_successors(dfd.df, options.successor_of_task, options.label)
        sys.exit(0)

    # These options can be cumulative and all require a --task parameter to select tasks
    if not options.task:
        print '--task <task_regex> is required'
        sys.exit(1)
    # A common mistake is to forget the head "." before a star ("*.vcpu0")
    # Better detect and fix to avoid frustration
    if options.task.startswith("*"):
        options.task = "." + options.task

    # create heatmaps only if one cdict was given
    if options.heatmaps:
        if len(dfds) == 1:
            create_heatmaps(dfds[0], cap_time, options.task, options.label)
        else:
            print 'Error: --heat-maps requires 1 cdict file only'
            sys.exit(1)
    else:
        create_charts(dfds, cap_time, options.task, options.label)

if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        print
        traceback.print_exc()
        print
        sys.exit(1)
