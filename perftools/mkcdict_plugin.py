

import credentials
import os
import re
from novaclient.client import Client


# ESC_Day0-3__62940__MT__MTPerftest_FULL_01ESC_Day0-31.1__0__CSR__0
instance_re = re.compile('ESC_Day0-3__\d*__MT__MTPerftest_FULL_(\d*)ESC_Day0-31.1__0__([A-Z]*)_')

# A dict of full names indexed by the uuid
#
# ESC_Day0-3__62940__MT__MTPerftest_FULL_01ESC_Day0-31.1__0__CSR__0
# becomes 'CSR.1'
by_uuid = {}

def decode_instance_name(name):
    m = instance_re.match(name)
    if m:
        chain_id = m.group(1)
        nvf = m.group(2)
        return int(chain_id), nvf
    return None, None

CFG_FILE = '.mkcdict.cfg'

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
            full_name = '%s.%d' % (nvf, chain_id)
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
