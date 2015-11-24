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


from bokeh.plotting import output_file

# Standard title attribute for all figures
title_style = {'title_text_font_size': '12pt',
               'title_text_font_style': 'bold'}

grid_title_style = {'title_text_font_size': '10pt',
                    'title_text_font_style': 'bold'}

def set_html_file(cdict_file):
    global html_file
    html_file = cdict_file.replace('.cdict', '')

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
