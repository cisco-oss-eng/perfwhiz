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

# Common functions across capture and map functions

import csv
import marshal
import os
import re
import zlib
try:
    # try to use the faster version if available
    from msgpack import packb
    from msgpack import unpackb
except ImportError:
    # else fall back to the pure python version (slower)
    from umsgpack import packb
    from umsgpack import unpackb

# a dict of task names indexed by tid
name_by_tid = {}
plugin_convert_name = None

def init(opts):
    global plugin_convert_name
    # try to import, can raise ImportError (no plugin found)
    # or plugin_init can raise ValueError
    from mkcdict_plugin import plugin_init
    print 'Initializing plugin...'
    if plugin_init(opts):
        from mkcdict_plugin import plugin_convert_name
        print 'Plugin initialized successfully'

uuid_re = re.compile('-uuid ([a-fA-F0-9\-]*)')
# /proc/pid/cpuset output
# /machine/instance-000065d7.libvirt-qemu/emulator
# /machine/instance-000065d3.libvirt-qemu/vcpu0
cpuset_re = re.compile('/machine/(instance-[a-fA-F0-9]*).libvirt-qemu/(\w*)')

def decode_cpuset(pid):
    name = None
    thread_type = None
    try:
        with open('/proc/%d/cpuset' % (pid)) as f:
            cpuset = f.read()
            res = cpuset_re.match(cpuset)
            if res:
                name = res.group(1)
                thread_type = res.group(2)
    except IOError:
        # some pids/tids come and go so just forget about this one
        pass
    return name, thread_type

def decode_pid(pid):
    name = None
    uuid = None
    thread_type = None
    try:
        with open('/proc/%d/cmdline' % (pid)) as f:
            cmdline = f.read()
            # this is a nul separated tokens
            cmdline = cmdline.replace('\x00', ' ')
            if cmdline.startswith('/usr/bin/qemu-system'):
                res = uuid_re.search(cmdline)
                if res:
                    uuid = res.group(1)
                    name, thread_type = decode_cpuset(pid)
    except IOError:
        # some pids/tids come and go so just forget about this one
        pass
    return name, uuid, thread_type

def get_task_name(tid, name):
    if not tid:
        return name
    try:
        return name_by_tid[tid]
    except KeyError:
        pass
    # check if it is a kvm thread from the look of the name
    libvirt_name, uuid, thread_type = decode_pid(tid)
    if libvirt_name:
        if plugin_convert_name:
            name = plugin_convert_name(name, tid, libvirt_name, uuid, thread_type)
        # append the thread type to the name
        name += '.' + thread_type
    name_by_tid[tid] = name
    return name

# cdict management functions

def remap(perf_dict, csv_map):
    '''Remap all the task names in the cdict file with those specified in the mapping file
    :param perf_dict: an uncompressed dictionary
    :param csv_map: csv mapping file name
    '''
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

def open_cdict(cdict_file, map_file=None):
    '''Open and decode a cdict file
    :param cdict_file: name of the cdict file
    :param map_file: name of a mapping file (optional)
    :return: the uncompressed dictionary representing the cdict file
    '''
    if not cdict_file.endswith('.cdict'):
        # automatically add the cdict extension if there is one
        if os.path.isfile(cdict_file + '.cdict'):
            cdict_file += '.cdict'
        else:
            raise ValueError('cdict file name must have the .cdict extension: ' + cdict_file)

    with open(cdict_file, 'r') as ff:
        cdict = ff.read()

    decomp = zlib.decompress(cdict)
    try:
        perf_dict = unpackb(decomp)
    except Exception:
        # old serialization format
        perf_dict = marshal.loads(decomp)
    if map_file:
        remap(perf_dict, map_file)
    return perf_dict

def write_cdict(cdict_file, perf_dict):
    '''Write a dictionary to a cdict file
    :param cdict_file: cdict file name (will auto add a .cdict extension if missing)
    :param perf_dict:  perf dict to compress and write
    :return:
    '''
    if not cdict_file.endswith('.cdict'):
        # automatically add the cdict extension if there is one
        cdict_file += '.cdict'
    with open(cdict_file, 'w') as ff:
        compressed = zlib.compress(packb(perf_dict))
        ff.write(compressed)
        print 'Compressed dictionary written to %s %d entries size=%d bytes' % \
              (cdict_file, len(perf_dict), len(compressed))
