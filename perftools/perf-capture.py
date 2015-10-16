#
# A wrapper around the perf tool to capture various data related to context switches and
# KVM events
#
import os
import sys
from optparse import OptionParser
import re
import subprocess
import perf_formatter

from mkcdict_perf_script import trace_begin
from mkcdict_perf_script import trace_end
from mkcdict_perf_script import add_event
from mkcdict_perf_script import kvm_entry
from mkcdict_perf_script import kvm_exit

# Curate the task names for a latency table
#  ---------------------------------------------------------------------------------------------------------------
#  Task                  |   Runtime ms  | Switches | Average delay ms | Maximum delay ms | Maximum delay at     |
# ---------------------------------------------------------------------------------------------------------------
#  qemu-system-x86:13568 |      5.762 ms |      102 | avg:    0.008 ms | max:    0.015 ms | max at: 9695849.502350 s
#  apache2:24581         |      0.397 ms |       10 | avg:    0.010 ms | max:    0.013 ms | max at: 9695849.359025 s
# The qemu task names need to be transformed into
# a type (emulator or vcpu0)
# By default, qemu-system-x86:13568 becomes qemu.vcpu0:13568 (for example)
#

def get_curated_latency_table(table):
    lines = table.split('\n')
    results = []
    for line in lines:
        index = line.find('|')
        if index <= 0:
            results.append(line)
            continue
        tname = line[:index]
        trailer = line[index:]
        # count how many spaces at head
        non_space = 0
        len_tname = len(tname)
        while non_space < len_tname and tname[non_space] == ' ':
            non_space += 1
        tname = tname[non_space:]
        if tname.startswith('qemu-'):
            index = tname.rfind(':')
            if index > 0:
                tid = int(tname[index + 1:])
                header = ' ' * non_space
                tname = perf_formatter.get_task_name(tid, 'qemu') + ':' + str(tid)
                # if needed add more space to keep alignment of next column
                pad_len = len_tname - non_space - len(tname)
                if pad_len > 0:
                    tname += ' ' * pad_len
                line = header + tname + trailer
        results.append(line)
    return '\n'.join(results)

def perf_record(opts, cs, kvm):
    perf_cmd = ['perf', 'sched', 'record']
    if cs:
        perf_cmd += ['-e', 'sched:*']
    if kvm:
        perf_cmd += ['-e', 'kvm:*']
    perf_cmd += ['sleep', str(opts.seconds)]
    rc = subprocess.call(perf_cmd)
    if rc:
        print 'Error recording traces'
        print 'You might need to run this script as root or with sudo'
        return False
    return True

def capture_stats(opts, cs=False, kvm=False):
    if perf_record(opts, cs, kvm):
        if cs:
            # perf sched latency -s switch
            cmd = ['perf', 'sched', 'latency', '-s', 'switch']
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=None)
            results, errors = process.communicate()
            if errors:
                print 'Error displaying scheduling latency'
            else:
                # curate the process names before displaying
                print get_curated_latency_table(results)
        if kvm:
            rc = subprocess.call(['perf', 'kvm', 'stat', 'report'])
            if rc:
                print 'Error displaying kvm stats'


def _kvm_entry(cpu, secs, nsecs, pid, comm, args):
    # kvm:kvm_entry: vcpu 0
    kvm_entry(cpu, secs, nsecs, pid, comm)

kvm_exit_re = re.compile('reason (\w*) ')
def _kvm_exit(cpu, secs, nsecs, pid, comm, args):
    #
    # kvm:kvm_exit: reason APIC_ACCESS rip 0xffffffff810271ee info 10b0 0
    m = kvm_exit_re.match(args)
    if m:
        kvm_exit(cpu, secs, nsecs, pid, comm, m.group(1))
    else:
        print 'Dropped mismatch for kvm_exit: ' + args


# sched:sched_switch: prev_comm=qemu-system-x86 prev_pid=28823 prev_prio=120 prev_state=S ==>
# next_comm=swapper/7 next_pid=0 next_prio=120
switch_re = re.compile('comm=([\w\-/]+) prev_pid=(\d+) prev_prio=\d+ prev_state=\w* ==> '
                       'next_comm=([\w\-/]+) next_pid=(\d+) ')

def sched_switch(cpu, secs, nsecs, pid, comm, args):

    print 'sched switch:' + args
    m = switch_re.match(args)
    if m:
        add_event('sched:sched_switch', cpu, secs, nsecs, m.group(2), m.group(1), 0, m.group(4), m.group(3))
    else:
        print 'Dropped mismatch for sched_stat_runtime: ' + args

# sched:sched_stat_runtime: comm=qemu-system-x86 pid=28823 runtime=36140 [ns] vruntime=3273999068253 [ns]
stat_runtime_re = re.compile('comm=([\w\-/]+) pid=(\d+) runtime=(\d)+ ')

def sched_stat_runtime(cpu, secs, nsecs, pid, comm, args):
    m = stat_runtime_re.match(args)
    if m:
        add_event('sched:sched_stat_runtime', cpu, secs, nsecs, m.group(2), m.group(1), m.group(3))
    else:
        print 'Dropped mismatch for sched_stat_runtime: ' + args

# sched:sched_stat_sleep: comm=qemu-system-x86 pid=28823 delay=386438 [ns]
stat_sleep_re = re.compile('comm=([\w\-/]+) pid=(\d+) delay=(\d)+ ')

def sched_stat_sleep(cpu, secs, nsecs, pid, comm, args):
    m = stat_sleep_re.match(args)
    if m:
        add_event('sched:sched_stat_sleep', cpu, secs, nsecs, m.group(2), m.group(1), m.group(3))
    else:
        print 'Dropped mismatch for sched_stat_sleep: ' + args

fn_dispatch = {
    'kvm_entry': _kvm_entry,
    'kvm_exit': _kvm_exit,
    'sched_switch': sched_switch,
    'sched_stat_runtime': sched_stat_runtime,
    'sched_stat_sleep': sched_stat_sleep
}


def decode_perf_text(filename):
    #  qemu-system-x86 27637 [006] 622048.897809: kvm:kvm_entry: vcpu 0
    trace_re = re.compile(' *([\w\-]*) *(\d*) \[(\d*)\] (\d*)\.(\d*): \w*:(\w*): ')
    with open(filename, 'r') as input:
        trace_begin()
        for line in input:
            if line[0] == '#':
                continue
            m = trace_re.match(line)
            if m:
                task = m.group(1)
                pid = int(m.group(2))
                cpu = int(m.group(3))
                secs = int(m.group(4))
                usecs = int(m.group(5))
                event = m.group(6)
                event_args = line[m.end():]
                try:
                    fn_dispatch[event](cpu, secs, usecs * 1000, pid, task, event_args)
                except KeyError:
                    pass
        trace_end()

def decode_txt():
    #  qemu-system-x86 27637 [006] 622048.897809: kvm:kvm_entry: vcpu 0
    trace_re = re.compile(' *([\w\-]*) *(\d*) \[(\d*)\] (\d*)\.(\d*): \w*:(\w*): ')
    with open('abc.txt', 'r') as input:
        for line in input:
            if line[0] == '#':
                continue
            m = trace_re.match(line)
            if m:
                task = m.group(1)
                pid = int(m.group(2))
                cpu = int(m.group(3))
                secs = int(m.group(4))
                usecs = int(m.group(5))
                event = m.group(6)
                event_args = line[m.end():]
                try:
                    fn_dispatch[event](event_args)
                except KeyError:
                    print 'unknown:' + event
                    pass
            else:
                print 'cannot decode:' + line
        sys.exit(0)

def capture_traces(cdict_filename, opts, kvm_events=False):
    # If it is a .data file we either need a python enabled perf tool (if available)
    # or we need to generate the text file from the perf tool and parse it (much slower)
    if cdict_filename.lower() == "none":
        filename = None
        cdict_filename = None
    else:
        filename, extension = os.path.splitext(cdict_filename)
        if extension != 'cdict':
            cdict_filename += '.cdict'

    # If this is set we skip the capture
    perf_data_filename = opts.perf_data
    if perf_data_filename:
        if not os.path.isfile(perf_data_filename):
            print 'Cannot find perf data file: ' + opts.perf_data
            return
    else:
        # need to capture traces
        if not perf_record(opts, True, kvm_events):
            return
        perf_data_filename = 'perf.data'
        print '   Traces captured in perf.data'

    # create cdict from the perf data file
    if cdict_filename:
        try:
            # try to run this script through the perf tool itself as it is faster
            rc = subprocess.call(['perf', 'script', '-s', 'mkcdict_perf_script.py', '-i', perf_data_filename],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if rc:
                print '   perf is not built with the python scripting extension, parsing text file (slower)...'
                text_filename = filename + '.txt'
                print '   generating text traces to file %s...' % (text_filename)
                with open(text_filename, 'w') as ff:
                    rc = subprocess.call(['perf', 'script', '-i', perf_data_filename],
                                         stdout=ff, stderr=subprocess.PIPE)
                # parse the text file into a cdict file
                print '   Feature not implemented'
            else:
                # success result is in perf.cdict, so need to rename it
                os.rename('perf.cdict', cdict_filename)
                print '   Created file: ' + cdict_filename
        except OSError:
            print 'perf does not seems to be installed - exiting...'
            sys.exit(1)
    else:
        print '   Skipping creation of cdict file'

if __name__ == '__main__':
    parser = OptionParser(usage="usage: %prog [options]")

    parser.add_option('--cs-stats', dest='cs_stats',
                      action='store_true',
                      help='display curated context switches stats to stdout')

    parser.add_option('--kvm-stats', dest='kvm_stats',
                      action='store_true',
                      help='display kvm exit stats to stdout')

    parser.add_option('--all-stats', dest='all_stats',
                      action='store_true',
                      help='display all stats to stdout')

    parser.add_option('--switches', dest='cs_traces',
                      action='store',
                      help='capture detailed context switch traces and create cdict if not none',
                      metavar='<cdict file or "none">')

    parser.add_option('--kvm-switches', dest='cs_kvm_traces',
                      action='store',
                      help='capture detailed context switch and kvm traces and create cdict if not none',
                      metavar='<cdict file or "none">')

    parser.add_option('-s', '--sleep', dest='seconds',
                      action='store',
                      default=1,
                      help='capture duration in seconds, defaults to 1 second',
                      metavar='<seconds>')

    parser.add_option('--use-perf-data', dest='perf_data',
                      action='store',
                      help='use given perf data file (do not capture)',
                      metavar='<perf data file>')

    parser.add_option('-r', '--rc', dest='rc',
                      action='store',
                      help='source OpenStack credentials from rc file',
                      metavar='<openrc_file>')

    parser.add_option('-p', '--password', dest='passwordd',
                      action='store',
                      help='OpenStack password',
                      metavar='<password>')

    (opts, args) = parser.parse_args()

    #decode_txt()

    if opts.perf_data and not os.path.isfile(opts.perf_data):
        print 'Cannot find perf data file: ' + opts.perf_data
        sys.exit(1)

    try:
        perf_formatter.init(opts)
    except ImportError:
        print 'Using default qemu task name mapping (no plugin found)'
    except ValueError:
        print 'Using default qemu task name mapping (OpenStack credentials not found, use -r or env variables)'

    if opts.cs_traces:
        capture_traces(opts.cs_traces, opts)
    elif opts.cs_kvm_traces:
        capture_traces(opts.cs_kvm_traces, opts, kvm_events=True)
    elif opts.all_stats:
        capture_stats(opts, cs=True, kvm=True)
    else:
        if opts.cs_stats:
            capture_stats(opts, cs=True)
        if opts.kvm_stats:
            capture_stats(opts, kvm=True)
