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
from CsmakeSwiftProvider.SwiftProvider import SwiftProvider

class SwiftWrapper(CsmakeModuleAllPhase):
    """Library: csmake-swift-provider
       Purpose: Creates and provides information for a container that holds
                an entire release set
       Options:
           account - SwiftAccount reference - must be authorized to create containers
           container - Name of the container to use for the wrapper
           access - (OPTIONAL) SwiftAccounts that will be authorized as readers
       Phase: prep - set up wrapper
              getinfo - used by a wrapper aspect to obtain wrapper info
              * - any other phase will just return information about wrapper
       Returns: container name
       Environment: Upon succesful execution of the wrapper section
                    for every phase except getinfo,
                    the wrapper will insert '__wrapper__<id>'
                    into the csmake environment.  This environment definition
                    must exist in order for a wrapper to be later referred to
                    and populated - this allows for the definition of a
                    wrappering process that is ignored if no such wrapper
                    is actually established."""

    REQUIRED_OPTIONS = ['account', 'container']

    def prep(self, options):
        #Ensure container exists
        connectParams, _ = SwiftProvider.getAccount(
            self.engine,
            options['account'],
            self.engine.getPhase())
        client = SwiftProvider.getConnection(connectParams)
        SwiftProvider.ensureContainer(client, options['container'])
        if 'access' in options:
            SwiftProvider.setContainerAccounts(
                self.engine,
                'Read',
                client,
                options['container'],
                options['access'],
                'prep' )
        self.log.passed()
        return self.default(options)

    def getinfo(self, options):
        self.log.passed()
        return (options['container'], options['account'])

    def default(self, options):
        myid = self.calledId
        if '@' in myid:
            myid = myid.split('@')[1]
        self.env.env['__wrapper__%s' % myid] = 'Exists'
        self.log.passed()
        return (options['container'], options['account'])
