#!/usr/bin/env python
#
# Alec Hothan
# ---------------------------------------------------------


from optparse import OptionParser
import os
import sys
import itertools
#
# Import reusable code from pnstk.py
#

import marshal
import msgpack
import zlib
import pandas

from bokeh.plotting import figure, output_file, show
from bokeh.models.sources import ColumnDataSource
from bokeh.palettes import Spectral6
from pandas import DataFrame

# Global variables

# start analysis after first from_time usec
from_time = 0
# cap input file to first cap_time usec, 0 = unlimited
cap_time = 0

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

def output_html(chart_type, task_list=[]):
    filename = html_file + '_' + chart_type
    for task in task_list:
        filename += '_' + task.replace(':', '.')
    filename += '.html'
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

def show_task_heatmap(df, task, label):
    df, task = get_full_task_name(df, task)
    if not task:
        return
    # these are the 2 main events to show
    legend_map = {
        'sched__sched_stat_sleep': (RED, 'wakeup from sleep (y=sleep time)'),
        # 'sched__sched_stat_runtime': (GREEN, 'switched out from cpu (y=run time)')
        'sched__sched_switch': (GREEN, 'switched out from cpu (y=run time)')
    }

    p = figure(plot_width=1000, plot_height=1000, y_axis_type="log",
               title_text_font_size='14pt',
               title_text_font_style = "bold")
    p.xaxis.axis_label = 'time (usecs)'
    p.yaxis.axis_label = 'duration (usecs)'
    p.legend.orientation = "bottom_right"
    p.xaxis.axis_label_text_font_size = "10pt"
    p.yaxis.axis_label_text_font_size = "10pt"
    p.title = "Context switches %s (%s)" % (task, label)
    p.ygrid.minor_grid_line_color = 'navy'
    p.ygrid.minor_grid_line_alpha = 0.1

    for event in legend_map:
        dfe = df[df.event == event]
        dfe = dfe[dfe['duration'] > 0]
        count = len(dfe)
        color, legend_text = legend_map[event]
        legend_text = '%s (%d)' % (legend_text, count)
        p.circle('usecs', 'duration', source=ColumnDataSource(dfe),
                 size=get_disc_size(count),
                 color=color,
                 alpha=0.3,
                 legend=legend_text)

    # specify how to output the plot(s)
    output_html('thm', [task])

    # display the figure
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

def show_kvm_heatmap(df, task, label):
    df, task = get_full_task_name(df, task)
    if not task:
        return
    # these are the 2 main events to show
    legend_map = {
        'kvm_exit': (GREEN, 'vcpu running (y=vcpu run time)'),
        'kvm_entry': (RED, 'vcpu not running (y=kvm+sleep time)')
    }

    p = figure(plot_width=1000, plot_height=800, y_axis_type="log",
               title_text_font_size='14pt',
               title_text_font_style = "bold")
    p.xaxis.axis_label = 'time (usecs)'
    p.yaxis.axis_label = 'duration (usecs)'
    p.legend.orientation = "bottom_right"
    p.xaxis.axis_label_text_font_size = "10pt"
    p.yaxis.axis_label_text_font_size = "10pt"
    p.title = "KVM entries and exits for %s (%s)" % (task, label)
    p.ygrid.minor_grid_line_color = 'navy'
    p.ygrid.minor_grid_line_alpha = 0.1
    accumulated_time = {}
    total_time = 0
    for event in legend_map:
        dfe = df[df.event == event]
        count = len(dfe)
        color, legend_text = legend_map[event]
        legend_text = '%s (%d)' % (legend_text, len(dfe))
        # there is bug in bokeh when there are too many circles to draw, nothing is visible
        if len(dfe) > 50000:
            dfe = dfe[:50000]
            print 'Series for %s display truncated to 50000 events' % (event)
        p.circle('usecs', 'duration', source=ColumnDataSource(dfe),
                 size=get_disc_size(count),
                 color=color,
                 alpha=0.3,
                 legend=legend_text)
        event_duration = dfe['duration'].sum()
        accumulated_time[event] = event_duration
        total_time += event_duration

    # specify how to output the plot(s)
    output_html('kvm', [task])

    # display the figure
    show(p)

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

def show_core_locality(df, task_re, label):

    df = df[df['event'] == 'sched__sched_switch']
    df = df[df['task_name'].str.match(task_re)]
    task_list = pandas.unique(df.task_name.ravel())

    p = figure(plot_width=1000, plot_height=800,
               title_text_font_size='14pt',
               title_text_font_style = "bold")

    p.xaxis.axis_label = 'time (usecs)'
    p.yaxis.axis_label = 'core'
    p.legend.orientation = "bottom_right"
    p.xaxis.axis_label_text_font_size = "10pt"
    p.yaxis.axis_label_text_font_size = "10pt"
    p.title = "Core locality (%s)" % (label)

    color_list = cycle_colors(task_list)

    for task, color in zip(task_list, color_list):
        dfe = df[df['task_name'] == task]
        tid = dfe['pid'].iloc[0]
        count = len(dfe)
        legend_text = '%s:%d (%d)' % (task, tid, count)
        p.circle('usecs', 'cpu', source=ColumnDataSource(dfe),
                 size=get_disc_size(count), color=color,
                 alpha=0.3,
                 legend=legend_text)

    # specify how to output the plot(s)
    output_html('cpuloc', task_list)

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
                    df.set_value(index, 'duration',runtime)
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
        compressed = zlib.compress(msgpack.packb(res))
        ff.write(compressed)
        print 'Compressed dictionary written to %s %d entries size=%d bytes' % \
              (new_cdict, len(df), len(compressed))

    with open(new_cdict, 'r') as ff:
        cdict = ff.read()

    perf_dict = msgpack.unpackb(zlib.decompress(cdict))
    df = DataFrame(perf_dict)


# ---------------------------------- MAIN -----------------------------------------

parser = OptionParser(usage="usage: %prog [options] <cdict_file>")

parser.add_option("-t", "--task",
                  dest="task",
                  metavar="task ID or name",
                  help="show thread context switch heat map (use numeric tid or task name)"
                  )
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
                  help="show core locality chart for tasks with matching name"
                  )
parser.add_option("--kvm-exits",
                  dest="kvm_exits",
                  metavar="task ID or name",
                  help="show thread kvm exits heat map"
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
parser.add_option("--convert",
                  dest="convert",
                  action="store",
                  metavar="new cdict file",
                  help="migrate to new encoding with runtime aggregation into switch"
                  )
(options, args) = parser.parse_args()

'''
df = DataFrame(  {'AAA': [0, 0, 0, 1,2,3,4,5,6,7,8,9,10],
                  'tid': [0, 0, 5, 5,5,5,5,5,5,5,5,5,5],
                  'next_comm': [0,0,0,0,44,0,12,0,0,0,0,0,0],
                  'event': ['any', 'kvm_exit',
                            'kvm_entry',
                            'kvm_exit','kvm_exit','sched__sched_switch',
                            'kvm_exit', 'sched__sched_switch',
                            'kvm_exit', 'kvm_exit', 'kvm_exit',
                            'sched__sched_switchB', 'kvm_exit']})
show_last_exit_reasons_before_switches(df, 5)
sys.exit(0)
'''


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
    perf_dict = msgpack.unpackb(decomp)
except (msgpack.exceptions.UnpackException, msgpack.exceptions.ExtraData):
    # old serialization format
    perf_dict = marshal.loads(decomp)

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
    show_task_heatmap(df, options.task, options.label)
elif options.kvm_exits:
    show_kvm_heatmap(df, options.kvm_exits, options.label)
elif options.successor_of_task:
    show_successors(df, options.successor_of_task, options.label)
elif options.convert:
    convert(df, options.convert)