# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
from Csmake.CsmakeModuleAllPhase import CsmakeModuleAllPhase

class KeystoneAccount(CsmakeModuleAllPhase):
    """Library: csmake-swift-provider
       Purpose: Provides keystone account information for authenticating
                with a keystone v3 service
       Options:
           user - keystone authentication user
           password - (OPTIONAL) keystone authentication password
               if left off, it is assumed the account will not be
               used to authenticate - only for communicating access roles
           account - keystone project name that user is a member of
           service - Authentication service for keystone (a URI)
               Example: http://keystone.client.local
           service-port - (OPTIONAL) default is 35357, keystone's auth port
           service-version - (OPTIONAL) default is 3 (will be used in the URL)
       Phase: *
       Returns: Tuple of (swift client account dictionary, options)
           Use the account dictionary with SwiftProvider.getConnection"""

    REQUIRED_OPTIONS = ['user', 'account', 'service']

    def default(self, options):
        servicePort = '35357'
        if 'service-port' in options:
            servicePort = options['service-port']
        authVersion = '3'
        if 'service-version' in options:
            authVersion = options['service-version']
        #TODO: Allow retries, and backoffs to be fine tuned
        client = {
            'authurl' : "%s:%s/v%s" % (
                options['service'],
                servicePort,
                authVersion),
            'user' : "%s:%s" % (options['account'], options['user']),
            'insecure' : True,
            'retries' : 10,
            'starting_backoff' : 15, #Seconds
            'max_backoff' : 90,
            'auth_version' : authVersion }
        self.log.devdebug("Returning account info: %s", str(client))
        if 'password' in options:
            client['key'] = options['password']
        self.log.passed()
        return (client, options)
