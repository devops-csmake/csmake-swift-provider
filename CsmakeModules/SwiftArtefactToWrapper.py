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
from Csmake.CsmakeAspect import CsmakeAspect
from CsmakeSwiftProvider.SwiftProvider import SwiftProvider
import time

class SwiftArtefactToWrapper(CsmakeAspect):
    """Library: csmake-swift-provider
       Purpose: To include a swift "soft link like" reference in a
                SwiftWrapper on a successful push phase
                This will only attempt to push an artefact if
                the wrapper has indicated it exists by adding
                '__wrapper__<id>' to the csmake environment
                where <id> == the wrapper option
       Options:
           wrapper - The wrapper to link against
       Joinpoints: passed__push - Add item(s) to wrapper
       Returns: container name
       Requirements: Decorated section must respond to _getPushedObjects"""

    REQUIRED_OPTIONS = ['wrapper']

    def passed__push(self, phase, options, instance, instancedict):
        #Get just the id of the wrapper
        wrapperid = options['wrapper']
        if '@' in wrapperid:
            wrapperid = wrapperid.split('@')[1]
        if '__wrapper__%s' % wrapperid not in self.env.env:
            self.log.passed()
            self.log.info("Wrapper %s is not in use, artefact will not be put in the wrapper", wrapperid)
            return False
        result = self.engine.launchStep(options['wrapper'], 'getinfo')
        if result is None or not result._didPass():
            self.log.failed()
            self.log.error("Wrapper '%s' is invalid", self['wrapper'])
            return False
        toContainer, account = result._getReturnValue('getinfo')
        swiftAccount, _ = SwiftProvider.getAccount(self.engine, account, 'push')
        client = SwiftProvider.getConnection(swiftAccount)

        objects = instance._getPushedObjects()
        for fromContainer, objectName in objects:
            self.log.debug(
                "Linking '%s'/'%s' to '%s'",
                fromContainer,
                objectName,
                toContainer )
            headers = {
                'X-Object-Manifest' : '%s/%s' % (
                    fromContainer, objectName ),
                'X-Object-Meta-CreateTime' : str(time.time()) }
            putResult = {}
            client.put_object(
                toContainer,
                objectName,
                None,
                headers=headers,
                response_dict=putResult)
        self.log.passed()
        return True
