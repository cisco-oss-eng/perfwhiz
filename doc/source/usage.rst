=====
Usage
=====

Examples of captures
--------------------

.. note:: an installation using pip will provide wrappers that can be called directly from the shell command line (e.g. "perfcap" or "perfmap").
These wrappers are not available with an installation using a git clone and the corresponding python scripts must be called using the python
executable (e.g. "python perfcap.py ...").

.. note:: trace captures *require root permission* (perfcap must be called by root or using sudo).

Capture context switch and kvm exit traces for 5 seconds and generate traces into test.cdict::

    perfcap -s 5 --all test

Capture all traces for 1 second and use the "tmap.csv" mapping file to assign logical task names to task IDs::

    perfcap --all --map tmap.csv test2

Traces will be stored in the corresponding cdict file (e.g. "test2.cdict").

Generate the cdict file for an existing perf data file and name the resulting cdict file "oldrun.cdict"::

    perfcap --use-perf-data perf.data oldrun



Examples of chart generation
----------------------------

Generate the basic dashboard containing charts for all tasks with a name ending with "vcpu0" from the "test.cdict" capture file::

    perfmap.py -t '*vcpu0' test.cdict

Generate the heatmaps dashboard containing charts for all tasks with a name ending with "vcpu0" from the "test.cdict" capture file for the first 1000ms of capture (for heatmaps using smaller windows might be required in order to limit the density of the heatmaps)::

    perfmap.py -t '*vcpu0' --heatmaps -c 1000 test.cdict


Only show 1000 msec of capture starting from 2 seconds past the start of capture for all tasks::

    perfmap.py -t '*' -c 1000 -f 2000 test.cdict

Generate the basic dashboard with diff charts for 2 capture files::

    perfmap.py -t '*vcpu0' test.cdict test2.cdict



Task Name Annotation
--------------------

Analyzing data with pid, tid and the raw task name may not always be optimal because numeric task/process IDs are not very meaningful
and the raw task name may be a generic name (such as "/usr/bin/qemu-system-x86_64" for a VM or "/usr/bin/python" for a python process). Annotating task names allows such non descript tasks to be renamed for chart display purpose.

One additional benefit of annotating task names is that it allows easier comparative analysis across runs that may involve re-launching the tested processes (and in that case will have different task or process IDs).

For example assume each run requires launching 2 groups of 2 instances of VMs where each VM instance plays a certain role in its own group (router and firewall role, each group has 1 router and 1 firewall VM, forming what is called a service chain).

Without annotation the analysis will have to work with generic names such as:

Run #1::

    - vm_router, pid1 (group 1)
    - vm_router, pid2 (group 2)
    - vm_firewall, pid3 (group 1)
    - vm_firewall, pid4 (group 2)

Run #2::

    - vm_router, pid5 (group 1)
    - vm_router, pid6 (group 2)
    - vm_firewall, pid7 (group 1)
    - vm_firewall, pid8 (group 2)

The group membership for each process is completely lost during capture, making comparative analysis extremely difficult as you'd need to make a mental association of pid1 to pid5, pid2 to pid6 etc...

Worst, with the use of default non decript names you'd have to juggle with tasks such as:

    - /usr/bin/qemu-system-x86_64, pid1
    - /usr/bin/qemu-system-x86_64, pid2
    - etc...

With annotation, the task name could reflect the role and group membership:

Run #1::

    - vm_router.1, pid9
    - vm_router.2, pid10
    - vm_firewall.1, pid11
    - vm_firewall.2, pid12

Run #2::

    - vm_router.1, pid13
    - vm_router.2, pid14
    - vm_firewall.1, pid15
    - vm_firewall.2, pid16

It is much easier to analyze for example how heat map tasks relate to group membership or how the vm.router in each group compare across the 2 runs.

Task name annotation is supported by both perfcap.py and perfmap.py.

The perfcap.py script supports annotating task names at capture time using either a CSV mapping file or the OpenStack plug-in.
Annotating will mean that the generic task name will be replaced by the annotated name right after the perf capture is done and while creating the cdict file.

The perfmap.py script supports annotating task names using the CSV mapping file method only. In this case, the task name replacement will happen
while loading the data from the cdict file.

In general it is better to annotate earlier (at capture time) as it results in annotated cdict files and will avoid having to tow along
the mapping file corresponding to each cdict file.


CSV Mapping file
----------------
A mapping file is a valid comma separated value (CSV) text file that has the following fields in each line:

CSV format::

    <tid>,<libvirt-instance-name>,<task-system-type>,<uuid>,<group-type>,<group-id>,<task-name>

.. csv-table:: CSV field description
    :header: "name", "description"

    "<tid>", "linux task ID (also called thread ID)"
    "<libvirt-instance-name>", "libvirt instance name (VM) - ignored"
    "<task-system-type>", "a task type (VM: emulator or vcpu task)"
    "<uuid>", "instance uuid (OpenStack instance) - ignored"
    "<group-type>", "type of grouping (e.g. service chain type name) - ignored"
    "<group-id>", "indentifier of the group to distinguish between multiple groups (e.g. service chain number)"
    "<task-name>", "name of the task - describes what the task does (e.g. firewall or router...)"

Example of mapping file::

    19236,instance-000019f4,vcpu0,8f81e3a1-3ebd-4015-bbee-e291f0672d02,FULL,5,Firewall
    453,instance-00001892,emulator,4a81e3cc-4de0-5030-cbfd-f3c43213c34b,FULL,2,Router

Equivalent simplified version::

    19236,,vcpu0,,,5,Firewall
    453,,emulator,,,2,Router

In the current version, the annotated name is calculated as::

    <task-name>.<group-id>.<task-system-type>

The <tid> is used as a key for matching perf records to annotated names (i.e. all perf records that have a tid matching
any entry in the mapping file will have their task name renamed using the above annotated name).
All other fields are therefore ignored.

Resulting annotated name from the above example::

    Firewall.05.vcpu0
    Router.02.emulator

The helper script create-vm-csv.sh that is included in the git repository illustrates how such csv file can be created before capturing the traces.


OpenStack Plug-In
-----------------
Task name mapping can be performed automatically when VMs are being launched by OpenStack. In that case, the perfcap.py script will query OpenStack to retrieve the list of VM instances and deduct the task name mapping by associating OpenStack instance information to the corresponding task ID.
This feature is still experimental and may be moved out of perfwhiz completely into a separate tool that generates the CSV mapping file from OpenStack queries.



