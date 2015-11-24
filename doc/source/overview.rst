========
Overview
========

This repository contains a set of python scripts for helping tune any Linux
system for performance and scale by leveraging the Linux perf tool and 
generate from the perf traces:

- context switch heat maps (temporal distribution of context switch events)
- KVM exit heat maps (temporam distribution of kvm entry and exit events)
- KVM exit types distribution stacked bar charts (exit type distribution per task)
- core locality heat maps (on which core does task run over time)
- task scheduler core assignment heat maps (run time % on each core per task - including IDLE time)
- task per core context switch count heat maps (how many context switches per core per task)

The capture script wraps around the Linux perf tool to capture events of
interest (such as context switches, and kvm events) and generates a much more
compact binary file to be used for analysis offline.

Heatmap Gallery
---------------

(to add sample html files with embedded Java Script - try it out for now if you're curious)

perfwhiz Workflow
------------------

.. image:: images/perfwhiz.png

