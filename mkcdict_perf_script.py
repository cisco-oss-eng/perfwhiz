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
from optparse import OptionParser
import re
import subprocess
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

import marshal
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
    res = {'event': event_name_list,
           'cpu': cpu_list,
           'usecs': usecs_list,
           'pid': pid_list,
           'task_name': comm_list,
           'duration': duration_list,
           'next_pid': next_pid_list,
           'next_comm': next_comm_list}
    print 'End of trace, marshaling and compressing...'
    compressed = zlib.compress(marshal.dumps(res))
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
    with open('/proc/%d/cpuset' % (pid)) as f:
        cpuset = f.read()
        res = cpuset_re.match(cpuset)
        if res:
            name = res.group(1)
            thread_type = res.group(2)
    return name, thread_type

def decode_pid(pid):
    name = None
    uuid = None
    thread_type = None
    with open('/proc/%d/cmdline' % (pid)) as f:
        cmdline = f.read()
        # this is a nul separated tokens
        cmdline = cmdline.replace('\x00', ' ')
        if cmdline.startswith('/usr/bin/qemu-system'):
            res = uuid_re.search(cmdline)
            if res:
                uuid = res.group(1)
                name, thread_type = decode_cpuset(pid)
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
        # append the thread type to the name
        name += '.' + thread_type
        if plugin_convert_name:
            name = plugin_convert_name(name, tid, libvirt_name, uuid, thread_type)

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
    duration_list.append(duration/1000)
    next_pid_list.append(next_pid)
    next_comm_list.append(get_final_name(next_pid, next_comm))

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
    pass


def sched__sched_wakeup(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        comm, pid, prio, success,
                        target_cpu):
    pass


def sched__sched_stat_runtime(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, runtime, vruntime):
    add_event(event_name, common_cpu, common_secs, common_nsecs, pid, comm, runtime)


def sched__sched_switch(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        prev_comm, prev_pid, prev_prio, prev_state,
                        next_comm, next_pid, next_prio):
    add_event(event_name, common_cpu, common_secs, common_nsecs, prev_pid, prev_comm, 0, next_pid, next_comm)


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
            self.exit_time =  add_kvm_event('kvm_exit', cpu, secs, nsecs, self.tid,
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
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "comm=%s, pid=%d\n" % \
          (comm, pid),


def sched__sched_pi_setprio(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            comm, pid, oldprio, newprio):
    pass


def sched__sched_stat_blocked(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, delay):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "comm=%s, pid=%d, delay=%u\n" % \
          (comm, pid, delay),


def sched__sched_stat_wait(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           comm, pid, delay):
    pass


def sched__sched_process_exec(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              filename, pid, old_pid):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "filename=%s, pid=%d, old_pid=%d\n" % \
          (filename, pid, old_pid),


def sched__sched_process_fork(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              parent_comm, parent_pid, child_comm, child_pid):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "parent_comm=%s, parent_pid=%d, child_comm=%s, " \
          "child_pid=%d\n" % \
          (parent_comm, parent_pid, child_comm, child_pid),


def sched__sched_process_wait(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "comm=%s, pid=%d, prio=%d\n" % \
          (comm, pid, prio),


def sched__sched_wait_task(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           comm, pid, prio):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "comm=%s, pid=%d, prio=%d\n" % \
          (comm, pid, prio),


def sched__sched_process_exit(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio):
    pass


def sched__sched_process_free(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio):
    pass


def sched__sched_migrate_task(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid, prio, orig_cpu,
                              dest_cpu):
    pass


def sched__sched_kthread_stop_ret(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  ret):
    pass


def sched__sched_kthread_stop(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              comm, pid):
    pass


def kvm__kvm_async_pf_completed(event_name, context, common_cpu,
                                common_secs, common_nsecs, common_pid, common_comm,
                                address, gva):
    pass


def kvm__kvm_async_pf_ready(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            token, gva):
    pass


def kvm__kvm_async_pf_not_present(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  token, gva):
    pass


def kvm__kvm_async_pf_doublefault(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  gva, gfn):
    pass


def kvm__kvm_try_async_get_page(event_name, context, common_cpu,
                                common_secs, common_nsecs, common_pid, common_comm,
                                gva, gfn):
    pass


def kvm__kvm_age_page(event_name, context, common_cpu,
                      common_secs, common_nsecs, common_pid, common_comm,
                      hva, gfn, referenced):
    pass


def kvm__kvm_fpu(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 load):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "load=%s\n" % \
          (symbol_str("kvm__kvm_fpu", "load", load)),


def kvm__kvm_mmio(event_name, context, common_cpu,
                  common_secs, common_nsecs, common_pid, common_comm,
                  type, len, gpa, val):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "type=%s, len=%u, gpa=%u, " \
          "val=%u\n" % \
          (symbol_str("kvm__kvm_mmio", "type", type), len, gpa, val),


def kvm__kvm_ack_irq(event_name, context, common_cpu,
                     common_secs, common_nsecs, common_pid, common_comm,
                     irqchip, pin):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "irqchip=%s, pin=%u\n" % \
          (symbol_str("kvm__kvm_ack_irq", "irqchip", irqchip), pin),


def kvm__kvm_msi_set_irq(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         address, data):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "address=%u, data=%s\n" % \
          (address,
           symbol_str("kvm__kvm_msi_set_irq", "data", data)),


def kvm__kvm_ioapic_set_irq(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            e, pin, coalesced):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "e=%s, pin=%d, coalesced=%u\n" % \
          (symbol_str("kvm__kvm_ioapic_set_irq", "e", e), pin, coalesced),


def kvm__kvm_set_irq(event_name, context, common_cpu,
                     common_secs, common_nsecs, common_pid, common_comm,
                     gsi, level, irq_source_id):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "gsi=%u, level=%d, irq_source_id=%d\n" % \
          (gsi, level, irq_source_id),


def kvm__kvm_userspace_exit(event_name, context, common_cpu,
                            common_secs, common_nsecs, common_pid, common_comm,
                            reason, errno):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "reason=%s, errno=%d\n" % \
          (symbol_str("kvm__kvm_userspace_exit", "reason", reason), errno),


def kvm__kvm_track_tsc(event_name, context, common_cpu,
                       common_secs, common_nsecs, common_pid, common_comm,
                       vcpu_id, nr_vcpus_matched_tsc, online_vcpus, use_master_clock,
                       host_clock):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "vcpu_id=%u, nr_vcpus_matched_tsc=%u, online_vcpus=%u, " \
          "use_master_clock=%u, host_clock=%s\n" % \
          (vcpu_id, nr_vcpus_matched_tsc, online_vcpus, use_master_clock,

           symbol_str("kvm__kvm_track_tsc", "host_clock", host_clock)),


def kvm__kvm_update_master_clock(event_name, context, common_cpu,
                                 common_secs, common_nsecs, common_pid, common_comm,
                                 use_master_clock, host_clock, offset_matched):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "use_master_clock=%u, host_clock=%s, offset_matched=%u\n" % \
          (use_master_clock,
           symbol_str("kvm__kvm_update_master_clock", "host_clock", host_clock),
           offset_matched),


def kvm__kvm_write_tsc_offset(event_name, context, common_cpu,
                              common_secs, common_nsecs, common_pid, common_comm,
                              vcpu_id, previous_tsc_offset, next_tsc_offset):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "vcpu_id=%u, previous_tsc_offset=%u, next_tsc_offset=%u\n" % \
          (vcpu_id, previous_tsc_offset, next_tsc_offset),


def kvm__vcpu_match_mmio(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         gva, gpa, write, gpa_match):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "gva=%u, gpa=%u, write=%u, " \
          "gpa_match=%u\n" % \
          (gva, gpa, write, gpa_match),


def kvm__kvm_emulate_insn(event_name, context, common_cpu,
                          common_secs, common_nsecs, common_pid, common_comm,
                          rip, csbase, len, insn,
                          flags, failed):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rip=%u, csbase=%u, len=%u, " \
          "insn=%s, flags=%s, failed=%u\n" % \
          (rip, csbase, len, insn,

           symbol_str("kvm__kvm_emulate_insn", "flags", flags),
           failed),


def kvm__kvm_skinit(event_name, context, common_cpu,
                    common_secs, common_nsecs, common_pid, common_comm,
                    rip, slb):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rip=%u, slb=%u\n" % \
          (rip, slb),


def kvm__kvm_invlpga(event_name, context, common_cpu,
                     common_secs, common_nsecs, common_pid, common_comm,
                     rip, asid, address):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rip=%u, asid=%d, address=%u\n" % \
          (rip, asid, address),


def kvm__kvm_nested_intr_vmexit(event_name, context, common_cpu,
                                common_secs, common_nsecs, common_pid, common_comm,
                                rip):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rip=%u\n" % \
          (rip),


def kvm__kvm_nested_vmexit_inject(event_name, context, common_cpu,
                                  common_secs, common_nsecs, common_pid, common_comm,
                                  exit_code, exit_info1, exit_info2, exit_int_info,
                                  exit_int_info_err, isa):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "exit_code=%s, exit_info1=%u, exit_info2=%u, " \
          "exit_int_info=%u, exit_int_info_err=%u, isa=%u\n" % \
          (symbol_str("kvm__kvm_nested_vmexit_inject", "exit_code", exit_code), exit_info1, exit_info2, exit_int_info,
           exit_int_info_err, isa),


def kvm__kvm_nested_vmexit(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           rip, exit_code, exit_info1, exit_info2,
                           exit_int_info, exit_int_info_err, isa):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rip=%u, exit_code=%s, exit_info1=%u, " \
          "exit_info2=%u, exit_int_info=%u, exit_int_info_err=%u, " \
          "isa=%u\n" % \
          (rip,
           symbol_str("kvm__kvm_nested_vmexit", "exit_code", exit_code),
           exit_info1, exit_info2, exit_int_info, exit_int_info_err, isa),


def kvm__kvm_nested_intercepts(event_name, context, common_cpu,
                               common_secs, common_nsecs, common_pid, common_comm,
                               cr_read, cr_write, exceptions, intercept):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "cr_read=%u, cr_write=%u, exceptions=%u, " \
          "intercept=%u\n" % \
          (cr_read, cr_write, exceptions, intercept),


def kvm__kvm_nested_vmrun(event_name, context, common_cpu,
                          common_secs, common_nsecs, common_pid, common_comm,
                          rip, vmcb, nested_rip, int_ctl,
                          event_inj, npt):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rip=%u, vmcb=%u, nested_rip=%u, " \
          "int_ctl=%u, event_inj=%u, npt=%u\n" % \
          (rip, vmcb, nested_rip, int_ctl,
           event_inj, npt),


def kvm__kvm_pv_eoi(event_name, context, common_cpu,
                    common_secs, common_nsecs, common_pid, common_comm,
                    apicid, vector):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "apicid=%u, vector=%d\n" % \
          (apicid, vector),


def kvm__kvm_eoi(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 apicid, vector):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "apicid=%u, vector=%d\n" % \
          (apicid, vector),


def kvm__kvm_apic_accept_irq(event_name, context, common_cpu,
                             common_secs, common_nsecs, common_pid, common_comm,
                             apicid, dm, tm, vec,
                             coalesced):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "apicid=%u, dm=%s, tm=%u, " \
          "vec=%u, coalesced=%u\n" % \
          (apicid,
           symbol_str("kvm__kvm_apic_accept_irq", "dm", dm),
           tm, vec, coalesced),


def kvm__kvm_apic_ipi(event_name, context, common_cpu,
                      common_secs, common_nsecs, common_pid, common_comm,
                      icr_low, dest_id):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "icr_low=%s, dest_id=%u\n" % \
          (symbol_str("kvm__kvm_apic_ipi", "icr_low", icr_low), dest_id),


def kvm__kvm_pic_set_irq(event_name, context, common_cpu,
                         common_secs, common_nsecs, common_pid, common_comm,
                         chip, pin, elcr, imr,
                         coalesced):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "chip=%u, pin=%u, elcr=%u, " \
          "imr=%u, coalesced=%u\n" % \
          (chip, pin, elcr, imr,
           coalesced),


def kvm__kvm_apic(event_name, context, common_cpu,
                  common_secs, common_nsecs, common_pid, common_comm,
                  rw, reg, val):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rw=%u, reg=%s, val=%u\n" % \
          (rw,
           symbol_str("kvm__kvm_apic", "reg", reg),
           val),


def kvm__kvm_cr(event_name, context, common_cpu,
                common_secs, common_nsecs, common_pid, common_comm,
                rw, cr, val):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rw=%u, cr=%u, val=%u\n" % \
          (rw, cr, val),


def kvm__kvm_msr(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 write, ecx, data, exception):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "write=%u, ecx=%u, data=%u, " \
          "exception=%u\n" % \
          (write, ecx, data, exception),


def kvm__kvm_page_fault(event_name, context, common_cpu,
                        common_secs, common_nsecs, common_pid, common_comm,
                        fault_address, error_code):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "fault_address=%u, error_code=%u\n" % \
          (fault_address, error_code),


def kvm__kvm_inj_exception(event_name, context, common_cpu,
                           common_secs, common_nsecs, common_pid, common_comm,
                           exception, has_error, error_code):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "exception=%s, has_error=%u, error_code=%u\n" % \
          (symbol_str("kvm__kvm_inj_exception", "exception", exception), has_error, error_code),


def kvm__kvm_inj_virq(event_name, context, common_cpu,
                      common_secs, common_nsecs, common_pid, common_comm,
                      irq):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "irq=%u\n" % \
          (irq),


def kvm__kvm_cpuid(event_name, context, common_cpu,
                   common_secs, common_nsecs, common_pid, common_comm,
                   function, rax, rbx, rcx,
                   rdx):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "function=%u, rax=%u, rbx=%u, " \
          "rcx=%u, rdx=%u\n" % \
          (function, rax, rbx, rcx,
           rdx),


def kvm__kvm_pio(event_name, context, common_cpu,
                 common_secs, common_nsecs, common_pid, common_comm,
                 rw, port, size, count):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rw=%u, port=%u, size=%u, " \
          "count=%u\n" % \
          (rw, port, size, count),


def kvm__kvm_hv_hypercall(event_name, context, common_cpu,
                          common_secs, common_nsecs, common_pid, common_comm,
                          rep_cnt, rep_idx, ingpa, outgpa,
                          code, fast):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "rep_cnt=%u, rep_idx=%u, ingpa=%u, " \
          "outgpa=%u, code=%u, fast=%u\n" % \
          (rep_cnt, rep_idx, ingpa, outgpa,
           code, fast),


def kvm__kvm_hypercall(event_name, context, common_cpu,
                       common_secs, common_nsecs, common_pid, common_comm,
                       nr, a0, a1, a2,
                       a3):
    print_header(event_name, common_cpu, common_secs, common_nsecs,
                 common_pid, common_comm)

    print "nr=%u, a0=%u, a1=%u, " \
          "a2=%u, a3=%u\n" % \
          (nr, a0, a1, a2,
           a3),


def trace_unhandled(event_name, context, event_fields_dict):
    print ' '.join(['%s=%s' % (k, str(v)) for k, v in sorted(event_fields_dict.items())])


def print_header(event_name, cpu, secs, nsecs, pid, comm):
    print "%-20s %5u %05u.%09u %8u %-20s " % \
          (event_name, cpu, secs, nsecs, pid, comm),
