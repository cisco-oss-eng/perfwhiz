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
import zlib

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
    except ImportError:
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

def sched__sched_stat_sleep(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            comm, pid, delay):
    # the delay (time slept) applies to comm/pid
    # not common_comm/common_pid
    add_event(event_name, common_cpu, common_secs, common_nsecs, pid, comm, delay)


def sched__sched_wakeup_new(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            comm, pid, prio, success,
                            target_cpu):
    drop_event(event_name)


def sched__sched_wakeup(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        comm, pid, prio, success,
                        target_cpu):
    drop_event(event_name)

# A dict of runtime delays accumulated indexed by cpu
runtime_by_cpu = {}

def sched__sched_stat_runtime(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, runtime, vruntime):
    try:
        runtime_by_cpu[common_cpu] += runtime
    except KeyError:
        # the counter is set in on the first sched switch for each cpu
        pass

def sched__sched_switch(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        prev_comm, prev_pid, prev_prio, prev_state,
                        next_comm, next_pid, next_prio):
    try:
        runtime = runtime_by_cpu[common_cpu]
        add_event(event_name, common_cpu, common_secs, common_nsecs, prev_pid, prev_comm, runtime, next_pid, next_comm)
    except KeyError:
        pass
    runtime_by_cpu[common_cpu] = 0

def sched__sched_stat_iowait(event_name, context, common_cpu,
                             common_secs, common_nsecs, common_pid, common_comm,
                             comm, pid, delay):
    add_event(event_name, common_cpu, common_secs, common_nsecs, pid, comm, delay)


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

def kvm__kvm_entry(event_name, context, common_cpu,
                   common_secs, common_nsecs, common_pid, common_comm,
                   vcpu_id):
    try:
        kt = kvm_time_dict[common_pid]
    except:
        kt = KvmTime(common_pid)
        kvm_time_dict[common_pid] = kt
    kt.add_entry(common_cpu, common_secs, common_nsecs, common_comm)

def kvm__kvm_exit(event_name, context, common_cpu,
                  common_secs, common_nsecs, common_pid, common_comm,
                  exit_reason, guest_rip, isa, info1,
                  info2):
    try:
        kt = kvm_time_dict[common_pid]
    except:
        kt = KvmTime(common_pid)
        kvm_time_dict[common_pid] = kt
    kt.add_exit(common_cpu, common_secs, common_nsecs, common_comm, exit_reason)

# These are scale down versions of kvm__kvm_entry/exit that only require the minimum arguments
# used for manual parsing when the perf python extension is not compiled in
def kvm_entry(common_cpu, common_secs, common_nsecs, common_pid, common_comm):
    try:
        kt = kvm_time_dict[common_pid]
    except:
        kt = KvmTime(common_pid)
        kvm_time_dict[common_pid] = kt
    kt.add_entry(common_cpu, common_secs, common_nsecs, common_comm)

def kvm_exit(common_cpu, common_secs, common_nsecs, common_pid, common_comm, exit_reason):
    try:
        kt = kvm_time_dict[common_pid]
    except:
        kt = KvmTime(common_pid)
        kvm_time_dict[common_pid] = kt
    kt.add_exit(common_cpu, common_secs, common_nsecs, common_comm, exit_reason)

def sched__sched_process_hang(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid):
    drop_event(event_name)


def sched__sched_pi_setprio(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            comm, pid, oldprio, newprio):
    drop_event(event_name)


def sched__sched_stat_blocked(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, delay):
    drop_event(event_name)


def sched__sched_stat_wait(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           comm, pid, delay):
    drop_event(event_name)


def sched__sched_process_exec(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              filename, pid, old_pid):
    drop_event(event_name)


def sched__sched_process_fork(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              parent_comm, parent_pid, child_comm, child_pid):
    drop_event(event_name)


def sched__sched_process_wait(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio):
    drop_event(event_name)


def sched__sched_wait_task(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           comm, pid, prio):
    drop_event(event_name)


def sched__sched_process_exit(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio):
    drop_event(event_name)


def sched__sched_process_free(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio):
    drop_event(event_name)


def sched__sched_migrate_task(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio, orig_cpu,
                              dest_cpu):
    drop_event(event_name)


def sched__sched_kthread_stop_ret(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  ret):
    drop_event(event_name)


def sched__sched_kthread_stop(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid):
    drop_event(event_name)


def kvm__kvm_async_pf_completed(event_name, context, common_cpu,
                                common_secs, common_nsecs, common_pid, common_comm,
                                address, gva):
    drop_event(event_name)


def kvm__kvm_async_pf_ready(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            token, gva):
    drop_event(event_name)


def kvm__kvm_async_pf_not_present(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  token, gva):
    drop_event(event_name)


def kvm__kvm_async_pf_doublefault(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  gva, gfn):
    drop_event(event_name)


def kvm__kvm_try_async_get_page(event_name, context, common_cpu,
                                common_secs, common_nsecs, common_pid, common_comm,
                                gva, gfn):
    drop_event(event_name)


def kvm__kvm_age_page(event_name, context, common_cpu,
                      common_secs, common_nsecs, common_pid, common_comm,
                      hva, gfn, referenced):
    drop_event(event_name)


def kvm__kvm_fpu(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 load):
    drop_event(event_name)


def kvm__kvm_mmio(event_name, context, common_cpu,
                  common_secs, common_nsecs, common_pid, common_comm,
                  type, len, gpa, val):
    drop_event(event_name)


def kvm__kvm_ack_irq(event_name, context, common_cpu,
                     common_secs, common_nsecs, common_pid, common_comm,
                     irqchip, pin):
    drop_event(event_name)


def kvm__kvm_msi_set_irq(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         address, data):
    drop_event(event_name)


def kvm__kvm_ioapic_set_irq(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            e, pin, coalesced):
    drop_event(event_name)


def kvm__kvm_set_irq(event_name, context, common_cpu,
                     common_secs, common_nsecs, common_pid, common_comm,
                     gsi, level, irq_source_id):
    drop_event(event_name)


def kvm__kvm_userspace_exit(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            reason, errno):
    drop_event(event_name)


def kvm__kvm_track_tsc(event_name, context, common_cpu,
                       common_secs, common_nsecs, common_pid, common_comm,
                       vcpu_id, nr_vcpus_matched_tsc, online_vcpus, use_master_clock,
                       host_clock):
    drop_event(event_name)


def kvm__kvm_update_master_clock(event_name, context, common_cpu,
                                 common_secs, common_nsecs, common_pid, common_comm,
                                 use_master_clock, host_clock, offset_matched):
    drop_event(event_name)


def kvm__kvm_write_tsc_offset(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              vcpu_id, previous_tsc_offset, next_tsc_offset):
    drop_event(event_name)


def kvm__vcpu_match_mmio(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         gva, gpa, write, gpa_match):
    drop_event(event_name)


def kvm__kvm_emulate_insn(event_name, context, common_cpu,
                          common_secs, common_nsecs, common_pid, common_comm,
                          rip, csbase, len, insn,
                          flags, failed):
    drop_event(event_name)


def kvm__kvm_skinit(event_name, context, common_cpu,
                    common_secs, common_nsecs, common_pid, common_comm,
                    rip, slb):
    drop_event(event_name)


def kvm__kvm_invlpga(event_name, context, common_cpu,
                     common_secs, common_nsecs, common_pid, common_comm,
                     rip, asid, address):
    drop_event(event_name)


def kvm__kvm_nested_intr_vmexit(event_name, context, common_cpu,
                                common_secs, common_nsecs, common_pid, common_comm,
                                rip):
    drop_event(event_name)


def kvm__kvm_nested_vmexit_inject(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  exit_code, exit_info1, exit_info2, exit_int_info,
                                  exit_int_info_err, isa):
    drop_event(event_name)


def kvm__kvm_nested_vmexit(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           rip, exit_code, exit_info1, exit_info2,
                           exit_int_info, exit_int_info_err, isa):
    drop_event(event_name)


def kvm__kvm_nested_intercepts(event_name, context, common_cpu,
                               common_secs, common_nsecs, common_pid, common_comm,
                               cr_read, cr_write, exceptions, intercept):
    drop_event(event_name)


def kvm__kvm_nested_vmrun(event_name, context, common_cpu,
                          common_secs, common_nsecs, common_pid, common_comm,
                          rip, vmcb, nested_rip, int_ctl,
                          event_inj, npt):
    drop_event(event_name)


def kvm__kvm_pv_eoi(event_name, context, common_cpu,
                    common_secs, common_nsecs, common_pid, common_comm,
                    apicid, vector):
    drop_event(event_name)


def kvm__kvm_eoi(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 apicid, vector):
    drop_event(event_name)


def kvm__kvm_apic_accept_irq(event_name, context, common_cpu,
                             common_secs, common_nsecs, common_pid, common_comm,
                             apicid, dm, tm, vec,
                             coalesced):
    drop_event(event_name)


def kvm__kvm_apic_ipi(event_name, context, common_cpu,
                      common_secs, common_nsecs, common_pid, common_comm,
                      icr_low, dest_id):
    drop_event(event_name)


def kvm__kvm_pic_set_irq(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         chip, pin, elcr, imr,
                         coalesced):
    drop_event(event_name)


def kvm__kvm_apic(event_name, context, common_cpu,
                  common_secs, common_nsecs, common_pid, common_comm,
                  rw, reg, val):
    drop_event(event_name)


def kvm__kvm_cr(event_name, context, common_cpu,
                common_secs, common_nsecs, common_pid, common_comm,
                rw, cr, val):
    drop_event(event_name)


def kvm__kvm_msr(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 write, ecx, data, exception):
    drop_event(event_name)


def kvm__kvm_page_fault(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        fault_address, error_code):
    drop_event(event_name)


def kvm__kvm_inj_exception(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           exception, has_error, error_code):
    drop_event(event_name)


def kvm__kvm_inj_virq(event_name, context, common_cpu,
                      common_secs, common_nsecs, common_pid, common_comm,
                      irq):
    drop_event(event_name)


def kvm__kvm_cpuid(event_name, context, common_cpu,
                   common_secs, common_nsecs, common_pid, common_comm,
                   function, rax, rbx, rcx,
                   rdx):
    drop_event(event_name)


def kvm__kvm_pio(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 rw, port, size, count, val=None):
    drop_event(event_name)


def kvm__kvm_hv_hypercall(event_name, context, common_cpu,
                          common_secs, common_nsecs, common_pid, common_comm,
                          rep_cnt, rep_idx, ingpa, outgpa,
                          code, fast):
    drop_event(event_name)


def kvm__kvm_hypercall(event_name, context, common_cpu,
                       common_secs, common_nsecs, common_pid, common_comm,
                       nr, a0, a1, a2,
                       a3):
    drop_event(event_name)

def kvm__kvm_ple_window(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        grow, vcpu_id, new, old):
    drop_event(event_name)

def trace_unhandled(event_name, context, event_fields_dict):
    print 'unhandled ' + event_name
    print ' '.join(['%s=%s' % (k, str(v)) for k, v in sorted(event_fields_dict.items())])
