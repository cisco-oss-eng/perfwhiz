#!/usr/bin/env python
# Copyright 2015 Cisco Systems, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
#
# Author: Alec Hothan
# ---------------------------------------------------------

# This is an example of plugin that will load the list of instances from OpenStack
# and extract the type of service and service chain name from the instance name
# and store the resulting descriptive string in a dictionary indexed by the uuid
#

import credentials
import os
import re
from novaclient.client import Client

# Config file to specify the OpenStack crendentials needed to connect to the controller
# The file must contain the rc variable to point to the OpenStack credentials file
# (as downloaded from the Horizon dashboard), for example:
# rc=../admin-oper.sh
CFG_FILE = '.mkcdict.cfg'

# Extract the VM type and service chain ID from the instance name
# ESC_Day0-3__68540__MT__MTPerftest-FULL-01ESC_Day0-31.1__0__ASA__0
# ESC_Day0-3__62940__MT__MTPerftest_FULL_01ESC_Day0-31.1__0__CSR__0
instance_re = re.compile('ESC_Day0-3__\d*__MT__MTPerftest.FULL.(\d*)ESC_Day0-31.1__0__([A-Z]*)_')

# A dict of full names indexed by the uuid
#
# ESC_Day0-3__62940__MT__MTPerftest_FULL_01ESC_Day0-31.1__0__CSR__0
# becomes 'CSR.01'
by_uuid = {}

def decode_instance_name(name):
    m = instance_re.match(name)
    if m:
        chain_id = m.group(1)
        nvf = m.group(2)
        return int(chain_id), nvf
    return None, None


class OptionsHolder(object):
    def __init__(self):
        # check if there is a config file in the current directory
        if os.path.isfile(CFG_FILE):
            # load options from the config file
            opt_re = re.compile(' *(\w*) *[=:]+ *([\w/\-\.]*)')
            with open(CFG_FILE, 'r') as ff:
                for line in ff:
                    m = opt_re.match(line)
                    if m:
                        setattr(self, m.group(1), m.group(2))


def plugin_init(opts=None):
    # Parse the credentials of the OpenStack cloud
    if not opts:
        opts = OptionsHolder()
    cred = credentials.Credentials(opts)
    creds_nova = cred.get_nova_credentials_v2()
    # Create the nova and neutron instances
    nova_client = Client(**creds_nova)

    opts = {'all_tenants': 1}
    servers = nova_client.servers.list(detailed=True, search_opts=opts)
    count = 0
    for server in servers:
        chain_id, nvf = decode_instance_name(server.name)
        if chain_id:
            full_name = '%s.%02d' % (nvf, chain_id)
            by_uuid[server.id] = full_name
            count += 1
    print 'Plugin loaded with %d service chain names from Nova' % (count)
    return True

def plugin_convert_name(name, tid, libvirt_name, uuid, thread_type):
    try:
        return by_uuid[uuid]
    except KeyError:
        by_uuid[uuid] = name
        return name
