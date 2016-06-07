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
import os
import webbrowser

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
    global headless_mode

    headless_mode = headless

    # the full prefix of the output file with directory pathname
    global output_file_prefix
    global ignore_task_re

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
def get_time_span_usec(df):
    min_usec = df['usecs'].iloc[0]
    max_usec = df['usecs'].iloc[-1]
    return max_usec - min_usec

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


def get_output_file_name(chart_type, task_re):
    filename = output_file_prefix + '-' + chart_type
    if ignore_task_re:
        filename += '.html'
    else:
        if task_re.startswith('.*'):
            # skip leading .* if present
            task_re = task_re[2:]
        filename += '_' + task_re + '.html'
    return filename

def output_svg_html(svg_html, chart_type, task_re):
    filename = get_output_file_name(chart_type, task_re)
    with open(filename, 'w') as dest:
        dest.write(svg_html)
        print('Saved to %s (%d Kbytes)' % (filename, len(svg_html) / 1000))
        if not headless_mode:
            # bring up the file in the default browser
            url = 'file://' + os.path.abspath(filename)
            webbrowser.open(url, new=2)

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

class DfDesc(object):
    '''A class to store a dataframe and its metadata:
    - time constrained df
    - multiplier (to indicate if the df is under sampled)
    - name
    '''
    def __init__(self, cdict_file, df, merge_sys_tasks=False, append_tid=False):
        # remove the cdict extension if any
        if cdict_file.endswith('.cdict'):
            cdict_file = cdict_file[:-6]
        self.name = cdict_file
        self.multiplier = 1.0
        self.df = df
        self.short_name = cdict_file
        self.from_usec = 0
        self.to_usec = 0
        if merge_sys_tasks:
            # aggregate all the per core tasks (e.g. swapper/0 -> swapper)
            self.df['task_name'] = self.df['task_name'].str.replace(r'/.*$', '')
        if append_tid:
            self.df['task_name'] = self.df['task_name'] + ':' + self.df['pid'].astype(str)

    def normalize(self, from_time_usec, to_time_usec):
        # remove all samples that are under the start time
        if from_time_usec:
            self.df = self.df[self.df['usecs'] >= from_time_usec]
        last_time_usec = self.df['usecs'].iloc[-1]
        if to_time_usec > last_time_usec:
            # eg if the requested cap is 1 sec and the df only contains
            # 500 msec of samples, the multiplier is 2.0
            self.multiplier = float(to_time_usec - from_time_usec) / (last_time_usec - from_time_usec)
        # remove all samples that are over the cap
        self.df = self.df[self.df['usecs'] <= to_time_usec]
        self.from_usec = from_time_usec
        self.to_usec = to_time_usec
