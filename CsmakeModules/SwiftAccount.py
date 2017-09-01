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

class SwiftAccount(CsmakeModuleAllPhase):
    """Library: csmake-swift-provider
       Purpose: Provides swift account information for authenticating
                with a swift service
       Options:
           user - swift authentication user
           password - (OPTIONAL) swift authentication password
               if left off, it is assumed the account will not be
               used to authenticate - only for communicating access roles
           account - swift tenant or account name
           service - Authentication service for swift (a URI)
               Example: http://swift.client.local
           service-port - (OPTIONAL) default is 8080, swift's auth port
           service-path - (OPTIONAL) default is auth, swift's auth svc.
           service-version - (OPTIONAL) default is 1.0 (will be used in the URL)
       Phase: *
       Returns: Tuple of (swift client account dictionary, options)
           Use the account dictionary with SwiftProvider.getConnection"""

    REQUIRED_OPTIONS = ['user', 'account', 'service']

    def default(self, options):
        servicePort = '8080'
        if 'service-port' in options:
            servicePort = options['service-port']
        servicePath = 'auth'
        if 'service-path' in options:
            servicePath = options['service-path']
        authVersion = '1.0'
        if 'service-version' in options:
            authVersion = options['service-version']
        #TODO: Allow retries, and backoffs to be fine tuned
        client = {
            'authurl' : "%s:%s/%s/v%s" % (
                options['service'],
                servicePort,
                servicePath,
                authVersion),
            'user' : "%s:%s" % (options['account'], options['user']),
            'insecure' : True,
            'retries' : 10,
            'starting_backoff' : 15, #Seconds
            'max_backoff' : 90 }
        self.log.devdebug("Returning account info: %s", str(client))
        if 'password' in options:
            client['key'] = options['password']
        self.log.passed()
        return (client, options)
