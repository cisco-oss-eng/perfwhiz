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
import pandas
from pandas import Series

from bokeh.models.sources import ColumnDataSource
from bokeh.models import HoverTool
from bokeh.io import vplot
from bokeh.charts import Bar
from bokeh.models.widgets import DataTable
from bokeh.models.widgets import TableColumn
from bokeh.models.widgets import NumberFormatter
from bokeh.models.widgets import StringFormatter

from perfmap_common import output_html

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
            df['task_name'] = df['task_name'].astype(str) + '-' + dfd.short_name
        # check the time span
        if dfd.multiplier >= 1.0:
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

def show_kvm_exit_types(dfds, cap_time_usec, task_re, label):

    # a dict of adjustment ratios indexed by task name for cdicts
    # that require count adjustment due to
    # capture window being too small
    df, adjust_count_ratios = aggregate_dfs(dfds, task_re)
    if df.empty:
        print 'Error: No kvm traces matching ' + task_re
        return

    # the next_comm column contains the exit code
    exit_codes = Series(KVM_EXIT_REASONS)
    # add  new column containing the exit reason in clear text
    df['exit_reason'] = df['next_comm'].map(exit_codes)

    df.drop(['cpu', 'duration', 'event', 'next_pid', 'pid', 'next_comm', 'usecs'], inplace=True, axis=1)

    # Get the list of exit reasons, sorted alphabetically
    reasons = pandas.unique(df.exit_reason.ravel()).tolist()
    reasons.sort()

    # group by task name then exit reasons
    gb = df.groupby(['task_name', 'exit_reason'])
    # number of exit types
    size_series = gb.size()
    df = size_series.to_frame('count')
    df.reset_index(inplace=True)

    if adjust_count_ratios:
        df['ratio'] = df['task_name'].map(adjust_count_ratios)
        df.fillna(1.0, inplace=True)
        df['count'] = (df['count'] * df['ratio']).astype(int)
        df.drop(['ratio'], inplace=True, axis=1)

    p = Bar(df, label='task_name', values='count', stack='exit_reason',
            title="KVM Exit count by type per task (%s, %d msec window)" %
                  (label, cap_time_usec // 1000),
            legend='top_right',
            tools="resize,hover,save",
            width=1000, height=800)
    p._xaxis.axis_label = "Task Name"
    p._xaxis.axis_label_text_font_size = "12pt"
    p._yaxis.axis_label = "Exit Count (sum)"
    p._yaxis.axis_label_text_font_size = "12pt"

    # Cannot find a way to display the exit reason in the tooltip
    # from bokeh.models.renderers import GlyphRenderer
    # glr = p.select(dict(type=GlyphRenderer))
    # bar_source = glr[0].data_source
    # print bar_source.data
    # bar_source = glr[1].data_source
    # bar_source.data['exit_reason'] = ['HOHO']
    hover = p.select(dict(type=HoverTool))
    hover.tooltips = OrderedDict([
        ("task", "$x"),
        # {"reason", "@exit_reason"},
        ("count", "@height")
    ])

    # table with counts
    gb = df.groupby(['exit_reason'])
    keys = gb.groups.keys()
    dfr_list = []
    for reason in keys:
        dfr = gb.get_group(reason)
        # drop the exit reason column
        dfr = dfr.drop(['exit_reason'], axis=1)
        # rename the count column with the reason name
        dfr.rename(columns={'count': reason}, inplace=True)
        # set the task name as the index
        dfr.set_index('task_name', inplace=True)
        dfr_list.append(dfr)
    # concatenate all task columns into 1 dataframe that has the exit reason as the index
    # counts for missing exit reasons will be set to NaN
    dft = pandas.concat(dfr_list, axis=1)
    dft.fillna(0, inplace=True)
    # Add a total column
    dft['TOTAL'] = dft.sum(axis=1)
    sfmt = StringFormatter(text_align='center', font_style='bold')
    nfmt = NumberFormatter(format='0,0')

    col_names = list(dft.columns.values)
    col_names.sort()
    # move 'TOTAL' at end of list
    col_names.remove('TOTAL')
    col_names.append('TOTAL')
    # convert index to column name
    dft.reset_index(level=0, inplace=True)
    dft.rename(columns={'index': 'Task'}, inplace=True)
    columns = [TableColumn(field=name, title=name, formatter=nfmt) for name in col_names]
    columns.insert(0, TableColumn(field='Task', title='Task', formatter=sfmt))
    table = DataTable(source=ColumnDataSource(dft), columns=columns, width=1000,
                      row_headers=False,
                      height='auto')
    output_html(vplot(p, table), 'kvm-types', task_re)

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
