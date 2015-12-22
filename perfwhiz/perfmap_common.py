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
# ---------------------------------------------------------
import pandas
import bokeh.plotting
from bokeh.plotting import output_file
import os

# Standard title attribute for all figures
title_style = {'title_text_font_size': '12pt',
               'title_text_font_style': 'bold'}

grid_title_style = {'title_text_font_size': '10pt',
                    'title_text_font_style': 'bold'}

def set_html_file(cdict_file, headless, label, output_dir):
    '''Sets the final html file name prefix and output directory
    if output_dir is None then use same output directory as cdict_file (can be relative)
    else use that directory

    prefix is set as following:
    if label is None use cdict basename, remove the .cdict extension and append the task_re
    else use label as prefix and do not append the task_re

    :param cdict_file: e.g. ../../perf.cdict
    :param headless:
    :param label: will replace all space with _
    :param output_dir:
    :return:
    '''
    global output_chart

    # the full prefix of the output file with directory pathname
    global output_file_prefix
    global ignore_task_re

    if headless:
        output_chart = bokeh.plotting.save
    else:
        output_chart = bokeh.plotting.show

    if label:
        ignore_task_re = True
        output_file_base = label.replace(' ', '-')
    else:
        ignore_task_re = False
        output_file_base = os.path.basename(cdict_file).replace('.cdict', '')

    if output_dir:
        output_file_dir = output_dir
    else:
        output_file_dir = os.path.dirname(cdict_file)

    if output_file_dir and output_file_dir[-1] != '/':
        output_file_dir += '/'
    output_file_prefix = output_file_dir + output_file_base

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

def get_disc_size(count):
    if count < 100:
        return 10
    if count < 500:
        return 8
    return 6

def output_html(chart, chart_type, task_re):
    filename = output_file_prefix + '-' + chart_type
    if ignore_task_re:
        filename += '.html'
    else:
        filename += '_' + task_re + '.html'
    bokeh.plotting.output_file(filename)
    print('Saved to ' + filename)
    output_chart(chart)

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

def aggregate_dfs(dfs, task_re, cap_time_usec):
    '''
    Aggregate dfs from multiple cdicts into 1 df that has the task names
    sufficed with the cdict name
    :param dfs: a dict of df keyed by the cdict file name
    :param task_re: regex for task names
    :param cap_time_usec: requested cap time
    :return: a tuple made of
        an aggregated df with annotated task names
        a dict of multipliers indexed by the annotated task name, corresponding to the
               ratio between the requested cap time and the cdict cap time (always >= 1.0)
               that should be used to adjust counts
    '''
    adjust_count_ratios = {}
    time_span_msec = 0
    captime_msec = float(cap_time_usec) / 1000
    # annotate the task name with the cdict ID it comes from
    dfl = []
    for key, df in dfs.iteritems():
        df = df[df['event'] == 'kvm_exit']
        df = df[df['task_name'].str.match(task_re)]
        # add the cdict name to the task name unless there is only 1 cdict file
        if len(dfs) > 1:
            df['task_name'] = df['task_name'].astype(str) + '-' + key
        # check the time span
        tspan_msec = get_time_span_msec(df)
        time_span_msec = max(time_span_msec, tspan_msec)
        adjust_ratio = captime_msec / tspan_msec
        if adjust_ratio >= 1.05:
            print
            print 'Warning: counts for %s will be multiplied by %f (capture time %d < %d)' % \
                  (key, adjust_ratio, tspan_msec, captime_msec)
            # all these task names require a count adjustment
            adjust_task_names = pandas.unique(df.task_name.ravel()).tolist()
            for atn in adjust_task_names:
                adjust_count_ratios[atn] = adjust_ratio
        dfl.append(df)
    df = pandas.concat(dfl)
    return df, adjust_count_ratios
