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
import threading

class SwiftPushArtefact(CsmakeModule):
    """Purpose: Push an artefact to a swift container
       Type: Module   Library: csmake-swift-provider
       Phase:
           prep - ensures the container in the mapping exists
           push - Will push the file(s) provided to the container
                  based on the mapping
       Maps:
             Designate files on the left to push
             The container name(s) on the right
                 if the right side contains a slash '/', the text to the
                 left of the first string will be considered the
                 container.  Leading with a slash will cause errors.
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used - if this is unacceptable,
                      then the "prep" phase can be avoided, and containers may
                      be managed with the swift client, or a different
                      section may be used to create the container)
           access - (OPTIONAL) SwiftAccount section ids that should be given
                     read access to the objects and container
           expires - (OPTIONAL) Specify the amount of time before
                                the artefact will expire.
                                w = weeks
                                d = days
                                h = hours
                                m = minutes
                                s = seconds
                        Space delimited
                        example: 2w 5d 1h 33s
                          2 weeks, 5 days, 1 hour and 33 seconds to expire
                        (can be in any order, but who does that???)
           progress - (OPTIONAL) When "False" will mute the reporting of
                      progress. Default "True"
    """

    REQUIRED_OPTIONS = ['account']

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

        for froms, tos in self.mapping.iterspecs():
            for container in tos:
                containerName, _ = SwiftProvider.getContainerAndFile(
                    None,
                    container['relLocation'] )
                SwiftProvider.ensureContainer(client, containerName)
                if 'access' in options:
                    SwiftProvider.setContainerAccounts(
                        self.engine,
                        'Read',
                        client,
                        containerName,
                        options['access'],
                        'prep')
        self.log.passed()
        return True

    def push(self, options):
        class UploadReportThread(threading.Thread):
            def __init__(
                innerself,
                total,
                fileobject,
                container,
                filename ):
                threading.Thread.__init__(innerself)
                innerself.stopping = False
                innerself.total = total
                innerself.fileobject = fileobject
                innerself.container = container
                innerself.filename = filename
                innerself.starttime = None
                innerself.reporttime = None
                innerself.previousamount = 0

            def run(innerself):
                innerself.starttime = datetime.datetime.utcnow()
                innerself.reporttime = innerself.starttime
                try:
                    counter=0
                    while not innerself.stopping:
                        time.sleep(0.1)
                        counter += 1
                        if counter % 20:
                            continue
                        current = innerself.fileobject.tell()
                        percent = float(current)/float(innerself.total) * 100.0
                        if not innerself.stopping:
                            currenttime = datetime.datetime.utcnow()
                            delta = currenttime - innerself.reporttime
                            deltaXmitted = current - innerself.previousamount
                            if delta.total_seconds() > 0.0:
                                rate = float(deltaXmitted)/float(delta.total_seconds())/1000.0
                            else:
                                rate = 0.0
                            rateunit = "KB"
                            if rate > 1000.0:
                                rate /= 1000.0
                                rateunit = "MB"
                            if rate > 1000.0:
                                rate /= 1000.0
                                rateunit = "GB"
                            innerself.previousamount = current
                            innerself.reporttime = currenttime
                            if percent > 100.0:
                                percent = 100.0
                            self.log.info("[%s:%s] Transferred %d%% (%d out of %d  - %2.2f%s/s)",
                                innerself.container,
                                innerself.filename,
                                percent, current, innerself.total, rate, rateunit)
                except:
                    self.log.exception("Couldn't show progress")
                return 0

            def stop(innerself):
                innerself.stopping = True

        self.reportProgress = True
        if 'progress' in options:
            self.reportProgress = options['progress'] == 'True'
        self._dontValidateFiles()
        secondsToExpire = None
        if 'expires' in options:
            secondsToExpire = int(SwiftProvider.timeDeltaDisgronifier(
                options['expires']).total_seconds())
        #Execute the account section to get the account info
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'push')
        client = SwiftProvider.getConnection(clientParams)

        #Upload the requested objects in the mapping
        for froms, tos in self.mapping.iterspecs():
            for filename in froms:
                relfilename = filename['relLocation']
                if relfilename.startswith('./'):
                    relfilename = relfilename[2:]
                with open(filename['location'], 'rb', 0) as openFile:
                    self.log.debug("Using raw buffer, 10240 chunk size")
                    openFile.seek(0, os.SEEK_END)
                    fileSize = openFile.tell()
                    openFile.seek(0)
                    headers={'X-Object-Meta-CreateTime' : str(time.time())}
                    if secondsToExpire is not None:
                        headers.update({
                            'X-Delete-After' : str(secondsToExpire)})
                    for container in tos:
                        containerName, toFileName = SwiftProvider.getContainerAndFile(
                            relfilename,
                            container['relLocation'] )

                        if self.reportProgress:
                            reporter = UploadReportThread(
                                fileSize,
                                openFile,
                                containerName,
                                 toFileName )
                            reporter.start()

                        client.put_object(
                            containerName,
                            toFileName,
                            openFile,
                            content_length=fileSize,
                            chunk_size=10240,
                            headers=headers )

                        if self.reportProgress:
                            reporter.stop()
                            reporter.join()

                        self.objects.append((containerName, toFileName))

        self.log.passed()
        return True
