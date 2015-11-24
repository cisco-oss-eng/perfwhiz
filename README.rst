
========================
perftools for Linux perf
========================

This repository contains a set of python scripts for helping tune any Linux system for performance and scale by
leveraging the Linux perf tool and generate from the perf traces:

- context switch heat maps (temporal distribution of context switch events)
- KVM exit heat maps (temporam distribution of kvm entry and exit events)
- KVM exit types distribution stacked bar charts (exit type distribution per task)
- core locality heat maps (on which core does task run over time)
- task scheduler core assignment heat maps (run time % on each core per task - including IDLE time)
- task per core context switch count heat maps (how many context switches per core per task)

The capture script wraps around the Linux perf tool to capture events of interest (such as context switches, and kvm events) and
generates a much more compact binary file to be used for analysis offline.


Heatmap Gallery
---------------

(to add sample html files with embedded Java Script - try it out for now if you're curious)

Perftools workflow
------------------

.. image:: images/perftools.png



Analyzing traces (perfmap.py)
--------------------------------

Pre-requisites
^^^^^^^^^^^^^^
In all cases you will need python 2.7 and pip installed.

On the Linux server under test, the only requirement is to have a version of perf with python scripting enabled installed.
Unfortunately, some Linux distros such as Ubuntu now only package a version of perf that does not support python scripting (this is a compile time option).
In this case you will need to recompile perf with the proper compile flag, which is annoying but not too difficult to do if you follow the instructions to the letter.

Virtual Environment
^^^^^^^^^^^^^^^^^^^

You may want to create a python virtual environment if you prefer to have isolation of python installations (this is recommended but optional).
For example:

.. code::

    virtualenv pft
    source pft/bin/activate

Remember to activate your virtual environment every time before installing or use the tool.

Binary Installation
^^^^^^^^^^^^^^^^^^^

(This will be provided later as a PyPI installation).


Source code Installation
^^^^^^^^^^^^^^^^^^^^^^^^

Clone the git repository and install the dependencies:

.. code::

    git clone git@github.com:cisco-oss-eng/perftools.git
    cd perftools
    pip install -r requirements.txt

To run the analyzer tool:

.. code::

    python perftools/perf-sched.py -h

You will need a cdict file to generate any heat map.


Verifying your installation
^^^^^^^^^^^^^^^^^^^^^^^^^^^


Capturing traces (perf-capture.py)
----------------------------------

Installation
^^^^^^^^^^^^

Task Name Annotation
--------------------
Analyzing data with pid, tid and the raw task name may not always be optimal because numeric task or process IDs are not very meaningful
and the raw task name may be a generic name (such as "/usr/bin/qemu-system-x86_64" for a VM or "/usr/bin/python" for a python process).

One additional benefit of annotating task names is that it allows easier comparative analysis across runs that involve re-launching the tested processes.
For example assume each run requires launching 2 groups of 2 instances of VMs where each VM instance plays a certain role in its own group.

Without annotation the analysis will have to work with generic names such as:

Run #1:

- vm_router, pid1 (group 1)
- vm_router, pid2 (group 2)
- vm_firewall, pid3 (group 1)
- vm_firewall, pid4 (group 2)

Run #2:

- vm_router, pid5 (group 1)
- vm_router, pid6 (group 2)
- vm_firewall, pid7 (group 1)
- vm_firewall, pid8 (group 2)

The group membership for each process is completely lost during capture, making comparative analysis extremely difficult as you'd need to
associate pid1 to pid5, pid2 to piud6 etc...

With annotation, the task name could reflect the role and group membership:

Run #1:

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

Task name annotation is supported by both perf-capture.py and perf-sched.py.

The perf-capture.py script supports annotating task names at capture time using either a CSV mapping file or the OpenStack plug-in.
Annotating will mean that the generic task name will be replaced by the annotated name right after the perf capture is done and while creating the cdict file.

The perf-sched.py script supports annotating task names using the CSV mapping file method only. In this case, the task name replacement will happen
while loading the data from the cdict file.

In general it is better to annotate earlier (at capture time) as it results in annotated cdict files and will avoid having to tow along
the mapping file corresponding to each cdict file.


CSV Mapping file
^^^^^^^^^^^^^^^^

OpenStack Plug-In
^^^^^^^^^^^^^^^^^
