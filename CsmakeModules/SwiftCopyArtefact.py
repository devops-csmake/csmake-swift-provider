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
import swiftclient.exceptions
import fnmatch
import threading
import time

class SwiftCopyArtefact(CsmakeModule):
    """Library: csmake-swift-provider
       Purpose: Copy artefacts from a swift container to another.
       Phase:
           prep - ensures the push container exists
           push - Will push the file(s) provided to the container
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used - if this is unacceptable,
                      then the "prep" phase can be avoided, and containers may
                      be managed with the swift client, or a different
                      section may be used to create the container)
           container - Container to copy the artefact(s) to
           from-container - Container to copy the artefact(s) from
           objects - (OPTIONAL) The objects to copy (either newline or comma
                     delimited) from the container.  Posix file wildcards like
                     '*' and '?' can be used.
                     Default is to specify ('*')
           latest-only - (OPTIONAL) if True, then only the latest match is
                                    pulled from each object listed.
           access - (OPTIONAL) SwiftAccount section ids that should be given
                     read access to the objects and container
           expires - (OPTIONAL) Specify the amount of time before
                                the artefact will expire
                                                      w = weeks
                                d = days
                                h = hours
                                m = minutes
                                s = seconds
                        Space delimited
                        example: 2w 5d 1h 33s
                          2 weeks, 5 days, 1 hour and 33 seconds to expire"""

    REQUIRED_OPTIONS = ['account', 'container', 'from-container']

    def __init__(self, env, log):
        CsmakeModule.__init__(self, env, log)
        self.objects = []

    def _getPushedObjects(self):
        return self.objects

    def prep(self, options):
        #Execute the account section to get the account info
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'prep')
        client = SwiftProvider.getConnection(clientParams)

        SwiftProvider.ensureContainer(client, options['container'])
        if 'access' in options:
            SwiftProvider.setContainerAccounts(
                self.engine,
                'Read',
                client,
                options['container'],
                options['access'],
                'prep')
        self.log.passed()
        return True

    def push(self, options):
        secondsToExpire = None
        if 'expires' in options:
            secondsToExpire = int(SwiftProvider.timeDeltaDisgronifier(
                options['expires']).total_seconds())

        #Execute the account section to get the account info
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'push')
        client = SwiftProvider.getConnection(clientParams)

        class CopyThread(threading.Thread):
            def __init__(
                innerself,
                toContainer,
                objectTarget,
                fromContainer,
                toObjectName ):

                threading.Thread.__init__(innerself)
                innerself.fromContainer = fromContainer
                innerself.toContainer = toContainer
                innerself.objectTarget = objectTarget
                innerself.toObjectName = toObjectName
                innerself.succeeded = False

            def run(innerself):
                try:
                    client = SwiftProvider.getConnection(clientParams)
                    response = {}
                    deleteat = 9999999999
                    if secondsToExpire is not None:
                        deleteat = secondsToExpire
                    client.put_object(
                        innerself.toContainer,
                        innerself.objectTarget,
                        None,
                        headers={
                           'X-Copy-From' : '%s/%s' % (
                              options['from-container'],
                              innerself.objectTarget),
                           'X-Object-Meta-CreateTime' : str(time.time()),
                           'X-Delete-At': deleteat},
                    response_dict=response)
                    innerself.succeeded = True
                except swiftclient.exceptions.ClientException as e:
                    if e.http_status == 404 or e.http_status == 409:
                        self.log.warning(
                            "Copy of object '%s/%s' returned: %d",
                            options['from-container'],
                            innerself.objectTarget,
                            e.http_status )
                        self.log.warning(
                            "Step will not fail as this file was likely deleted but not yet removed from the container")
                        innerself.succeeded=True
                    else:
                        self.log.exception(
                            "Copy of object '%s/%s' failed",
                            options['from-container'],
                            innerself.objectTarget )

            def passed(innerself):
                return innerself.succeeded

        container = options['container']

        filematchers = ['*']
        if 'objects' in options:
            filematchers = ','.join(options['objects'].split('\n')).split(',')

        targetedObjects = SwiftProvider.getContainerListing(
            client,
            options['from-container'],
            filematchers,
            'latest-only' in options and options['latest-only'] == 'True' )

        threads = []
        for objectTarget in targetedObjects.keys():
            #TODO: Allow a mapping to another name
            self.log.info("Copying object: '%s'", objectTarget)
            threads.append(
                CopyThread(
                    options['container'],
                    objectTarget,
                    options['from-container'],
                    objectTarget ) )
            threads[-1].start()

        for thread in threads:
            thread.join()
            if not thread.passed():
                self.log.failed()
                return False

        self.log.passed()
        return True
