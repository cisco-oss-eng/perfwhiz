============
Perfwhiz FAQ
============


Can I get charts for existing perf data files?
----------------------------------------------
Yes it is possible to generate cdict files from existing perf binary data files. You just need to make sure that
the perf capture includes context switching events (and kvm evemts if needed).
Use the perfcap tool with the --use-perf-data argument to pass the perf data file (see usage)

