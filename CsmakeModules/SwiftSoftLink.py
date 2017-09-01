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
import time


class SwiftSoftLink(CsmakeModule):
    """Library: csmake-swift-provider
       Purpose: Create a soft link for an artefact in swift.
                This can be used as a no-op to set up a
                soft link into a wrapper using SwiftArtefactToWrapper
                or a similar aspect.
       Phase:
           prep - ensures the push container exists
           push - Will push soft links based on the provided options
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used - if this is unacceptable,
                      then the "prep" phase can be avoided, and containers may
                      be managed with the swift client, or a different
                      section may be used to create the container)
           container - Container to link artefact(s) from
           to-container - (OPTIONAL) Container to link artefacts to
                              If this is unspecified anr/or noop is set to True
                              then this will set up parameters for an aspect
                              such as SwiftArtefactToWrapper
           files - (OPTIONAL) list of files (either newline or comma delimited)
                   to id from the container.  Posix file wildcards like '*'
                   and '?' can be used.
                   Default is to identify all of the files (i.e., '*').
           latest-only - (OPTIONAL) if True, then only the latest match is
                                    pulled from each file listed.
                         Default is False
           noop - (OPTIONAL) if True, then this will only set up parameters
                             as a SwiftPushArtefact would for an aspect like
                             SwiftArtefactToWrapper
           """

    REQUIRED_OPTIONS = ['account', 'container']

    def _getPushedObjects(self):
        return self.objects

    def __init__(self, env, log):
        CsmakeModule.__init__(self, env, log)
	self.objects = []

    def sources(self, options):
        self.pull(options)

    def _isNoop(self, options):
        return 'to-container' not in options or \
            ('noop' in options and options['noop'] == 'True' )

    def prep(self, options):
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'prep')
        client = SwiftProvider.getConnection(clientParams)
        if not self._isNoop(options):
            SwiftProvider.ensureContainer(
                client,
                options['to-container'])
        self.log.passed()
        return True

    def push(self, options):
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], "push")
        client = SwiftProvider.getConnection(clientParams)
        filematchers = ['*']
        if 'files' in options:
            filematchers = ','.join(options['files'].split('\n')).split(',')

        targetedObjects = SwiftProvider.getContainerListing(
            client,
            options['container'],
            filematchers,
            'latest-only' in options and options['latest-only'] == 'True' )

        targetPath = self.engine.resultsDir
        if 'result-dir' in options:
            targetPath = options['result-dir']

        threads = []

        for filename, (data, _) in targetedObjects.iteritems():
            self.objects.append((options['container'], filename))

            if not self._isNoop(options):
                headers = {
                    'X-Object-Manifest' : '%s/%s' % (
                        options['container'], filename ),
                    'X-Object-Meta-CreateTime' : str(time.time()) }
                putResult = {}
                client.put_object(
                    options['to-container'],
                    filename,
                    None,
                    headers=headers,
                    response_dict=putResult )

        self.log.passed()
        return True

