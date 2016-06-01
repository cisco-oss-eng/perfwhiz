#
# See the perf-trace-python Documentation for the list of available functions.
# perf python script for creating the cdict files out of a perf.data file
# To be used by the perf-sched post processing script.
#
# This script reads a perf binary file (through perf script -s) and generates a cdict file
# named perf.cdict.
# The cdict file is a compressed json dump of a python dictionary that contains
# a subset of the perf traces in a form that is ready to be loaded into a pandas dataframe.
#
# Functions in this script are also called from mkcdict.py when the python scripting of perf is not compiled in.
#
import os
import sys
from os.path import expanduser
import re
import zlib

# Location of the perf python helper files
try:
    sys.path.append(os.environ['PERF_EXEC_PATH'] +
                    '/scripts/python/perf-script-Util/lib/Perf/Trace')
except KeyError:
    pass
sys.path.append(expanduser('~/perf-trace-lib'))

try:
    from perf_trace_context import *
    from Core import *
except ImportError:
    pass

try:
    # try to use the faster version if available
    from msgpack import packb
except ImportError:
    # else fall back to the pure python version (slower)
    from umsgpack import packb

# pandas dataframe friendly data structures
event_name_list = []
cpu_list = []
usecs_list = []
pid_list = []
comm_list = []
duration_list = []
next_pid_list = []
next_comm_list = []

# a dict of task names indexed by tid
name_by_tid = {}

# A dict of counts indexed by event name
# counts how many are being ignored (not counted) in the cdict
event_drops = {}

# A dict of counts indexed by event name
# counts how many are being counted and added to the cdict
event_counts = {}

def drop_event(event_name):

    try:
        event_drops[event_name] += 1
    except KeyError:
        event_drops[event_name] = 1

def count_event(event_name):
    try:
        event_counts[event_name] += 1
    except KeyError:
        event_counts[event_name] = 1

def trace_begin():
    global plugin_convert_name

    # try to import
    try:
        from mkcdict_plugin import plugin_init
        print 'Initializing plugin...'
        if plugin_init():
            from mkcdict_plugin import plugin_convert_name
    except (ImportError, ValueError, Exception):
        plugin_convert_name = None

def trace_end():
    # report dropped kvm events
    print 'Dropped events (not stored in cdict file):'
    for name in sorted(event_drops, key=event_drops.get, reverse=True):
        print '   %6d %s' % (event_drops[name], name)
    print
    print 'Events stored in cdict file:'
    for name in sorted(event_counts, key=event_counts.get, reverse=True):
        print '   %6d %s' % (event_counts[name], name)
    print
    # build cdict
    res = {'event': event_name_list,
           'cpu': cpu_list,
           'usecs': usecs_list,
           'pid': pid_list,
           'task_name': comm_list,
           'duration': duration_list,
           'next_pid': next_pid_list,
           'next_comm': next_comm_list}
    print 'End of trace, marshaling and compressing...'
    compressed = zlib.compress(packb(res))
    with open('perf.cdict', 'w') as ff:
        ff.write(compressed)
    print 'Compressed dictionary written to perf.cdict %d entries size=%d bytes' % \
          (len(cpu_list), len(compressed))

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
        pass
    return name, uuid, thread_type

def get_final_name(tid, name):
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

def get_usecs(secs, nsecs):
    global epoch
    try:
        usecs = (secs * 1000000) + (nsecs / 1000) - epoch
    except NameError:
        epoch = (secs * 1000000) + (nsecs / 1000)
        usecs = 0
    return usecs

def add_event(name, cpu, secs, nsecs, pid, comm, duration=0, next_pid=0, next_comm=None):
    event_name_list.append(name)
    cpu_list.append(cpu)
    usecs_list.append(get_usecs(secs, nsecs))
    pid_list.append(pid)
    comm_list.append(get_final_name(pid, comm))
    # duration in usec
    duration_list.append(duration / 1000)
    next_pid_list.append(next_pid)
    next_comm_list.append(get_final_name(next_pid, next_comm))
    count_event(name)

def add_kvm_event(name, cpu, secs, nsecs, pid, comm, prev_usecs, reason=None):
    usecs = get_usecs(secs, nsecs)
    event_name_list.append(name)
    cpu_list.append(cpu)
    usecs_list.append(usecs)
    pid_list.append(pid)
    comm_list.append(get_final_name(pid, comm))
    duration_list.append(usecs - prev_usecs)
    next_pid_list.append(None)
    next_comm_list.append(reason)
    count_event(name)
    return usecs

#
# Due to a commit in the perf code that breaks compatibility with the perf python script
# we have to use list args for all callbacks in order to support perf versions
# pre and post patch (check commit 0f5f5bcd in the linux code):
# def sched__sched_stat_sleep(event_name, context, common_cpu,
# 	common_secs, common_nsecs, common_pid, common_comm,
# -	comm, pid, delay):
# +	common_callchain, comm, pid, delay):
#
# Luckily the positional arg is always inserted at the 8th position
#
# New version callback:
# def sched__sched_stat_sleep(event_name, context, common_cpu,
#                             common_secs, common_nsecs, common_pid, common_comm,
#                             common_callchain, comm, pid, delay):
# versus old version callback:
# def sched__sched_stat_sleep(event_name, context, common_cpu,
#                             common_secs, common_nsecs, common_pid, common_comm,
#                             common_callchain, comm, pid, delay):
# The fix for this is pick a default of new signature (always favor new versions)
# and if the argument list is 1 short of the target function arg list, then insert
# a None argument at position 8 (which is index 7 in the list) before calling the
# target function
#
def _dispatch(target, *args):
    arg_count = target.__code__.co_argcount
    if len(args) != arg_count:
        largs = list(args)
        largs.insert(7, None)
        args = tuple(largs)
        # note that any error case like arg list shorter than 7 or
        # signature mismatch after insertion will result in a runtime error
        # which is ok
    target(*args)

def _sched__sched_stat_sleep(event_name, context, common_cpu,
                             common_secs, common_nsecs, common_pid, common_comm,
                             common_callchain,
                             comm, pid, delay):
    # the delay (time slept) applies to comm/pid
    # not common_comm/common_pid
    add_event(event_name, common_cpu, common_secs, common_nsecs, pid, comm, delay)

def sched__sched_stat_sleep(*args):
    _dispatch(_sched__sched_stat_sleep, *args)

def sched__sched_wakeup_new(*args):
    drop_event(args[0])

def sched__sched_wakeup(*args):
    drop_event(args[0])

# A dict of runtime delays accumulated indexed by cpu
runtime_by_cpu = {}

def _sched__sched_stat_runtime(event_name, context, common_cpu,
                               common_secs, common_nsecs, common_pid, common_comm,
                               common_callchain,
                               comm, pid, runtime, vruntime):
    try:
        runtime_by_cpu[common_cpu] += runtime
    except KeyError:
        # the counter is set in on the first sched switch for each cpu
        pass

def sched__sched_stat_runtime(*args):
    _dispatch(_sched__sched_stat_runtime, *args)

def _sched__sched_switch(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         common_callchain,
                         prev_comm, prev_pid, prev_prio, prev_state,
                         next_comm, next_pid, next_prio):
    try:
        runtime = runtime_by_cpu[common_cpu]
        add_event(event_name, common_cpu, common_secs, common_nsecs, prev_pid, prev_comm, runtime, next_pid, next_comm)
    except KeyError:
        pass
    runtime_by_cpu[common_cpu] = 0

def sched__sched_switch(*args):
    _dispatch(_sched__sched_switch, *args)

def _sched__sched_stat_iowait(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              common_callchain,
                              comm, pid, delay):
    add_event(event_name, common_cpu, common_secs, common_nsecs, pid, comm, delay)

def sched__sched_stat_iowait(*args):
    _dispatch(_sched__sched_stat_iowait, *args)

class KvmTime(object):
    def __init__(self, tid):
        self.tid = tid
        # all units are usecs since beginning of traces
        self.entry_time = 0
        self.exit_time = 0

    def add_entry(self, cpu, secs, nsecs, comm):
        if self.exit_time:
            self.entry_time = add_kvm_event('kvm_entry', cpu, secs, nsecs, self.tid,
                                            comm, self.exit_time)
        else:
            self.entry_time = get_usecs(secs, nsecs)

    def add_exit(self, cpu, secs, nsecs, comm, reason):
        if self.entry_time:
            self.exit_time = add_kvm_event('kvm_exit', cpu, secs, nsecs, self.tid,
                                           comm, self.entry_time, reason)
        else:
            self.exit_time = get_usecs(secs, nsecs)

# A dict of last kvm entry/exit time indexed by tid
kvm_time_dict = {}

def _kvm__kvm_entry(event_name, context, common_cpu,
                    common_secs, common_nsecs, common_pid, common_comm,
                    common_callchain,
                    vcpu_id):
    try:
        kt = kvm_time_dict[common_pid]
    except:
        kt = KvmTime(common_pid)
        kvm_time_dict[common_pid] = kt
    kt.add_entry(common_cpu, common_secs, common_nsecs, common_comm)

def kvm__kvm_entry(*args):
    _dispatch(_kvm__kvm_entry, *args)

def _kvm__kvm_exit(event_name, context, common_cpu,
                   common_secs, common_nsecs, common_pid, common_comm,
                   common_callchain,
                   exit_reason, guest_rip, isa, info1,
                   info2):
    try:
        kt = kvm_time_dict[common_pid]
    except:
        kt = KvmTime(common_pid)
        kvm_time_dict[common_pid] = kt
    kt.add_exit(common_cpu, common_secs, common_nsecs, common_comm, exit_reason)

def kvm__kvm_exit(*args):
    _dispatch(_kvm__kvm_exit, *args)

def sched__sched_process_hang(*args):
    drop_event(args[0])

def sched__sched_pi_setprio(*args):
    drop_event(args[0])

def sched__sched_stat_blocked(*args):
    drop_event(args[0])

def sched__sched_stat_wait(*args):
    drop_event(args[0])

def sched__sched_process_exec(*args):
    drop_event(args[0])

def sched__sched_process_fork(*args):
    drop_event(args[0])

def sched__sched_process_wait(*args):
    drop_event(args[0])

def sched__sched_wait_task(*args):
    drop_event(args[0])

def sched__sched_process_exit(*args):
    drop_event(args[0])

def sched__sched_process_free(*args):
    drop_event(args[0])

def sched__sched_migrate_task(*args):
    drop_event(args[0])

def sched__sched_kthread_stop_ret(*args):
    drop_event(args[0])

def sched__sched_kthread_stop(*args):
    drop_event(args[0])

def kvm__kvm_async_pf_completed(*args):
    drop_event(args[0])

def kvm__kvm_async_pf_ready(*args):
    drop_event(args[0])

def kvm__kvm_async_pf_not_present(*args):
    drop_event(args[0])

def kvm__kvm_async_pf_doublefault(*args):
    drop_event(args[0])

def kvm__kvm_try_async_get_page(*args):
    drop_event(args[0])

def kvm__kvm_age_page(*args):
    drop_event(args[0])

def kvm__kvm_fpu(*args):
    drop_event(args[0])

def kvm__kvm_mmio(*args):
    drop_event(args[0])

def kvm__kvm_ack_irq(*args):
    drop_event(args[0])

def kvm__kvm_msi_set_irq(*args):
    drop_event(args[0])

def kvm__kvm_ioapic_set_irq(*args):
    drop_event(args[0])

def kvm__kvm_set_irq(*args):
    drop_event(args[0])

def kvm__kvm_userspace_exit(*args):
    drop_event(args[0])

def kvm__kvm_track_tsc(*args):
    drop_event(args[0])

def kvm__kvm_update_master_clock(*args):
    drop_event(args[0])

def kvm__kvm_write_tsc_offset(*args):
    drop_event(args[0])

def kvm__vcpu_match_mmio(*args):
    drop_event(args[0])

def kvm__kvm_emulate_insn(*args):
    drop_event(args[0])

def kvm__kvm_skinit(*args):
    drop_event(args[0])

def kvm__kvm_invlpga(*args):
    drop_event(args[0])

def kvm__kvm_nested_intr_vmexit(*args):
    drop_event(args[0])

def kvm__kvm_nested_vmexit_inject(*args):
    drop_event(args[0])

def kvm__kvm_nested_vmexit(*args):
    drop_event(args[0])

def kvm__kvm_nested_intercepts(*args):
    drop_event(args[0])

def kvm__kvm_nested_vmrun(*args):
    drop_event(args[0])

def kvm__kvm_pv_eoi(*args):
    drop_event(args[0])

def kvm__kvm_eoi(*args):
    drop_event(args[0])

def kvm__kvm_apic_accept_irq(*args):
    drop_event(args[0])

def kvm__kvm_apic_ipi(*args):
    drop_event(args[0])

def kvm__kvm_pic_set_irq(*args):
    drop_event(args[0])

def kvm__kvm_apic(*args):
    drop_event(args[0])

def kvm__kvm_cr(*args):
    drop_event(args[0])

def kvm__kvm_msr(*args):
    drop_event(args[0])

def kvm__kvm_page_fault(*args):
    drop_event(args[0])

def kvm__kvm_inj_exception(*args):
    drop_event(args[0])

def kvm__kvm_inj_virq(*args):
    drop_event(args[0])

def kvm__kvm_cpuid(*args):
    drop_event(args[0])

def kvm__kvm_pio(*args):
    drop_event(args[0])

def kvm__kvm_hv_hypercall(*args):
    drop_event(args[0])

def kvm__kvm_hypercall(*args):
    drop_event(args[0])

def kvm__kvm_ple_window(*args):
    drop_event(args[0])

def trace_unhandled(event_name, context, event_fields_dict):
    print 'unhandled ' + event_name
    print ' '.join(['%s=%s' % (k, str(v)) for k, v in sorted(event_fields_dict.items())])
