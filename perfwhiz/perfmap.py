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

from perf_formatter import open_cdict
from perf_formatter import write_cdict

from perfmap_common import set_html_file

from perfmap_kvm_exit_types import show_kvm_exit_types
from perfmap_sw_kvm_exits import show_sw_kvm_heatmap

from perfmap_core import show_core_runs
from perfmap_core import show_core_locality

# Global variables

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
    res = {'event': df['event'].tolist(),
           'cpu': df['cpu'].tolist(),
           'usecs': df['usecs'].tolist(),
           'pid': df['pid'].tolist(),
           'task_name': df['task_name'].tolist(),
           'duration': df['duration'].tolist(),
           'next_pid': df['next_pid'].tolist(),
           'next_comm': df['next_comm'].tolist()}
    write_cdict(new_cdict, res)

# ---------------------------------- MAIN -----------------------------------------
# Suppress future warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

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
parser.add_option("-t", "--task",
                  dest="task",
                  metavar="task name (regex)",
                  help="selected task(s) (regex on task name)"
                  )
parser.add_option("--core-locality",
                  dest="core_loc",
                  action="store_true",
                  help="show core locality heat map (requires --task)"
                  )
parser.add_option("--core-runtime",
                  dest="core_runtime",
                  action="store_true",
                  help="show % runtime on each core (requires --task)"
                  )
parser.add_option("--core-switch-count",
                  dest="core_switches",
                  action="store_true",
                  help="show context switch count on each core (requires --task)"
                  )
parser.add_option("--switches",
                  dest="switches",
                  action="store_true",
                  help="show context switches heat map (requires --task)"
                  )
parser.add_option("--kvm-exits",
                  dest="kvm_exits",
                  action="store_true",
                  help="show kvm exits heat map (requires --task)"
                  )
parser.add_option("--kvm-exit-types",
                  dest="kvm_exit_types",
                  action="store_true",
                  help="show kvm exit types bar charts (requires --task)"
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
perf_dict = open_cdict(cdict_file, options.map)

df = DataFrame(perf_dict)
set_html_file(cdict_file)

# filter on usecs
if from_time:
    df = df[df['usecs'] >= from_time]
if cap_time:
    df = df[df['usecs'] <= cap_time]

if not options.label:
    options.label = os.path.splitext(os.path.basename(cdict_file))[0]

if options.convert:
    convert(df, options.convert)
    sys.exit(0)

if options.show_tids:
    res = df.groupby(['pid', 'task_name']).size()
    res.sort_values(ascending=False, inplace=True)
    print 'List of tids and task names sorted by context switches and kvm event count'
    print res
    sys.exit(0)

if options.successor_of_task:
    show_successors(df, options.successor_of_task, options.label)
    sys.exit(0)

# These options can be cumulative and all require a --task parameter to select tasks
if not options.task:
    print '--task <task_regex> is required'
    sys.exit(1)

if options.core_runtime:
    show_core_runs(df, options.task, options.label, True)

if options.core_switches:
    show_core_runs(df, options.task, options.label, False)

if options.core_loc:
    show_core_locality(df, options.task, options.label)

if options.switches or options.kvm_exits:
    show_sw_kvm_heatmap(df, options.task, options.label, options.switches, options.kvm_exits)

if options.kvm_exit_types:
    show_kvm_exit_types(df, options.task, options.label)
