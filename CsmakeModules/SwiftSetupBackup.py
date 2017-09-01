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
from Csmake.CsmakeModule import CsmakeModule
from CsmakeSwiftProvider.SwiftProvider import SwiftProvider
import os
import datetime
import time
import urllib

class SwiftSetupBackup(CsmakeModule):
    """Library: csmake-swift-provider
       Purpose: Create a backup container for a Swift container
       Phase:
           prep - ensures the backup container exists and the container
                  to be backed up (or versioned) has the appropriate
                  metadata.  Backups will be performed automatically
                  when a file is replaced.
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used - if this is unacceptable,
                      then the "prep" phase can be avoided, and containers may
                      be managed with the swift client, or a different
                      section may be used to create the container)
           backup - Name of the backup container to create
           container - Name of the container to backup
           access - (OPTIONAL) SwiftAccount section ids that should be given
                     read access to the objects and container"""

    REQUIRED_OPTIONS = ['account', 'backup', 'container']

    def __init__(self, env, log):
        CsmakeModule.__init__(self, env, log)
        self.objects = []

    def _getPushedObjects(self):
        return self.objects

    def prep(self, options):
        self._dontValidateFiles()
        #Execute the account section to get the account info
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'prep')
        client = SwiftProvider.getConnection(clientParams)
        SwiftProvider.ensureContainer(client, options['backup'])
        if 'access' in options:
            SwiftProvider.setContainerAccounts(
                self.engine,
                'Read',
                client,
                options['backup'],
                options['access'],
                'prep' )
        
        mycontainer = client.get_container(options['container'])
        mycontainer[0]['name'] = options['container']
        self.log.devdebug("Container obtained: %s", str(mycontainer))
        SwiftProvider.addDetailsToAccountListing(client, [mycontainer])
        headers = SwiftProvider.getMetadataFromContainerDict(mycontainer[0])
        headers['x-versions-location']=urllib.quote(options['backup']) 
        client.post_container(options['container'], headers)

        self.log.passed()
        return True

