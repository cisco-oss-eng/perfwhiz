#

import re

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


