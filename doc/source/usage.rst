=====
Usage
=====

WIP

Task Name Annotation
--------------------

Analyzing data with pid, tid and the raw task name may not always be optimal because numeric task or process IDs are not very meaningful
and the raw task name may be a generic name (such as "/usr/bin/qemu-system-x86_64" for a VM or "/usr/bin/python" for a python process).

One additional benefit of annotating task names is that it allows easier comparative analysis across runs that involve re-launching the tested processes.
For example assume each run requires launching 2 groups of 2 instances of VMs where each VM instance plays a certain role in its own group.

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

The group membership for each process is completely lost during capture, making comparative analysis extremely difficult as you'd need to
associate pid1 to pid5, pid2 to piud6 etc...

With annotation, the task name could reflect the role and group membership:

Run #1::
    - vm_router.1, pid9
    - vm_router.2, pid10
    - vm_firewall.1, pid11
    - vm_firewall.2, pid12

Run #2:
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
    "<libvirt-instance-name>", "libvirt instance name (VM)"
    "<task-system-type>", "a task type (VM: emulator or vcpu task)"
    "<uuid>", "instance uuid (OpenStack instance)"
    "<group-type>", "type of grouping (e.g. service chain type name)"
    "<group-id>", "indentifier of the group to distinguish between multiple groups (e.g. service chain number)"
    "<task-name>", "name of the task - describes what the task does (e.g. firewall or router...)"

Example of mapping file::
    19236,instance-000019f4,vcpu0,8f81e3a1-3ebd-4015-bbee-e291f0672d02,FULL,5,Firewall
    453,instance-00001892,emulator,4a81e3cc-4de0-5030-cbfd-f3c43213c34b,FULL,2,Router

In the current version, the annotated name is calculated as::
    <task-name>.<group-id>.<task-system-type>

The <tid> is used as a key for matching perf records to annotated names (i.e. all perf records that have a tid matching
any entry in the mapping file will have their task name renamed using the above annotated name).
All other fields are therefore ignored.

Resulting annotated name from the above example::
    Firewall.05.vcpu0
    Router.02.emulator


OpenStack Plug-In
-----------------

