#!/bin/bash

PROG=$0

usage(){
   echo "Usage: $PROG <qemu-pid> <vm-type> <vm-id>"
   echo "<qemu-pid> the main pid for the VM"
   echo "<vm-type> the type of the VM - use a name desrcribing the type of function performed by the VM (e.g. "router")"
   echo "<vm-id> the instance ID the VM (e.g. "1") useful when there are multiple instances of the same VM type"
   echo
   echo "This script prints to stdout the mapping information for the given VM pid"
   echo "The output is usually redirected to a csv file, which can then be used to capture traces or remap traces (perfcap.py --map <csv-file>)"
   echo "It is very useful when working with KVM processes in order to distinguish all the different threads of a VM"
   echo "The pretty task name is computed by perfmap.py based on the values of the csv file"
   exit 1
}

test $# -eq 3 || usage

VMPID=$1
VMTYPE=$2
VMID=$3
TIDS=$(ls /proc/$VMPID/task)
emu_index=0
for tid in $TIDS
do
   cpuset=$(cat /proc/$tid/cpuset)
   task_type=$(basename $cpuset)
   if [ $task_type = "emulator" ]; then
       task_type="emulator${emu_index}"
       ((emu_index++))
   fi
   # format of the csv mapping row:
   # 19236,instance-000019f4,emulator,8f81e3a1-3ebd-4015-bbee-e291f0672d02,FULL,5,CSR
   echo "${tid},unused,${task_type},unused,unused,${VMID},${VMTYPE}"

done
