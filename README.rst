
========================
perftools for Linux perf
========================

This repository contains a set of python scripts for helping tune any Linux system for performance and scale by
leveraging the Linux perf tool and generate from the perf traces:

- context switch heat maps
- KVM exit heat maps
- core locality and core usage heat maps

The main scripts are:

- perf-capture.py
- perf-sched.py


Perftools workflow
------------------

.. image:: images/perftools.png

Installation and dependencies
-----------------------------

Capturing traces (perf-capture.py)
----------------------------------

Analyzing traces (perf-sched.py)
--------------------------------

