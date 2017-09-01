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
import fnmatch
import swiftclient

class SwiftCleanupContainers(CsmakeModule):
    """Library: csmake-swift-provider
       Purpose: Clean up containers that are empty and object links pointing
                to 404's
       Phase:
           push, enforce_policy, clean - Will execute the delete policy
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used)
           containers - Containers to cleanup
                     Posix file wildcards like '*' and '?' can be used."""

    REQUIRED_OPTIONS = ['account', 'containers']

    def clean(self, options):
        return self.push(options)

    def enforce_policy(self, options):
        return self.push(options)

    def push(self, options):

        #Execute the account section to get the account info
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'push')
        client = SwiftProvider.getConnection(clientParams)

        containerMatcher = ','.join(options['containers'].split('\n')).split(',')

        targetedContainers = SwiftProvider.getAccountListing(
            client,
            containerMatcher)

        for ctrname, container in targetedContainers.iteritems():
            targetedObjects = SwiftProvider.getContainerListing(
                client,
                ctrname )

            self.log.debug("In Container: %s", ctrname)
            containerlen = len(targetedObjects)
            self.log.debug("Items in container to examine: %d", containerlen)
            for objectName, objectShort in targetedObjects.iteritems():
                objectDetails = client.head_object(ctrname, objectName)
                if 'x-object-manifest' in objectDetails:
                    #Get the pointer(s) to the real object(s)
                    manifest = objectDetails['x-object-manifest']
                    if '/' not in manifest:
                        self.log.info("The object manifest for '%s' is not well formed: %s", objectName, manifest)
                        self.log.info("  --- skipping")
                        continue
                    realcontainer, realobject = manifest.split('/',1)
                    realobjects = SwiftProvider.getContainerListing(
                        client,
                        realcontainer,
                        ["%s*" % realobject] )
                    if len(realobjects) == 0:
                        #The object DNE
                        self.log.debug("The object link '%s' from '%s' didn't have a referant - deleting link file", manifest, objectName)
                        client.delete_object(ctrname, objectName)
                        containerlen = containerlen - 1
                    else:
                        self.log.debug("The object link '%s' from '%s' still has a referant", manifest, objectName)
                else:
                    self.log.debug("Object '%s' is not a link", objectName)
                    self.log.devdebug("   %s", str(objectDetails))
            if containerlen == 0:
                self.log.debug("Container: %s is now empty, removing container", ctrname)
                client.delete_container(ctrname)

        self.log.passed()
        return True
