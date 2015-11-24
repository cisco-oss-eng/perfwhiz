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

# Module for credentials in Openstack
import os
import re


class Credentials(object):

    def get_credentials(self):
        dct = {}
        dct['username'] = self.rc_username
        dct['password'] = self.rc_password
        dct['auth_url'] = self.rc_auth_url
        dct['tenant_name'] = self.rc_tenant_name
        return dct

    def get_nova_credentials(self):
        dct = {}
        dct['username'] = self.rc_username
        dct['api_key'] = self.rc_password
        dct['auth_url'] = self.rc_auth_url
        dct['project_id'] = self.rc_tenant_name
        return dct

    def get_nova_credentials_v2(self):
        dct = self.get_nova_credentials()
        dct['version'] = 2
        return dct

    #
    # Read a openrc file and take care of the password
    # The 2 args are passed from the command line and can be None
    #
    def __init__(self, opts):
        self.rc_password = None
        self.rc_username = None
        self.rc_tenant_name = None
        self.rc_auth_url = None
        openrc_file = None
        pwd = None

        try:
            pwd = opts.password
        except AttributeError:
            pass
        try:
            openrc_file = opts.rc
        except AttributeError:
            pass

        if openrc_file:
            if os.path.exists(openrc_file):
                export_re = re.compile('export OS_([A-Z_]*)="?(.*)')
                for line in open(openrc_file):
                    line = line.strip()
                    mstr = export_re.match(line)
                    if mstr:
                        name = mstr.group(1)
                        value = mstr.group(2)
                        if value.endswith('"'):
                            value = value[:-1]
                        # get rid of password assignment
                        # echo "Please enter your OpenStack Password: "
                        # read -sr OS_PASSWORD_INPUT
                        # export OS_PASSWORD=$OS_PASSWORD_INPUT
                        if value.startswith('$'):
                            continue
                        # now match against wanted variable names
                        if name == 'USERNAME':
                            self.rc_username = value
                        elif name == 'AUTH_URL':
                            self.rc_auth_url = value
                        elif name == 'PASSWORD':
                            self.rc_password = value
                        elif name == 'TENANT_NAME':
                            self.rc_tenant_name = value
            else:
                raise ValueError('rc file does not exist %s' % (openrc_file))
        else:
            # no openrc file passed - we assume the variables have been
            # sourced by the calling shell
            # just check that they are present
            for varname in ['OS_USERNAME', 'OS_AUTH_URL', 'OS_TENANT_NAME']:
                if varname not in os.environ:
                    raise ValueError('%s is missing' % (varname))
            self.rc_username = os.environ['OS_USERNAME']
            self.rc_auth_url = os.environ['OS_AUTH_URL']
            self.rc_tenant_name = os.environ['OS_TENANT_NAME']

        # always override with CLI argument if provided
        if pwd:
            self.rc_password = pwd
        # if password not know, check from env variable
        elif self.rc_auth_url and not self.rc_password:
            if 'OS_PASSWORD' in os.environ:
                self.rc_password = os.environ['OS_PASSWORD']
