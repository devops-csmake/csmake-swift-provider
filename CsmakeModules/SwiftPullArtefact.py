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
import os.path
import fnmatch
import threading
import datetime
import swiftclient.exceptions


class SwiftPullArtefact(CsmakeModule):
    """Purpose: Pull an artefact from a swift container
       Type: Module   Library: csmake-swift-provider
       Phase:
           sources, pull - Will pull the file(s) provided to the container
                  based on the mapping
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used - if this is unacceptable,
                      then the "prep" phase can be avoided, and containers may
                      be managed with the swift client, or a different
                      section may be used to create the container)
           container - Container to pull artefact(s) from
           files - (OPTIONAL) list of files (either newline or comma delimited)
                   to pull from the container.  Posix file wildcards like '*'
                   and '?' can be used.
                   Default is to pull all of the files (i.e., '*').
           latest-only - (OPTIONAL) if True, then only the latest match is
                                    pulled from each file listed.
                         Default is False
           result-dir - (OPTIONAL) The result directory to place the files
                         Default is csmake's target
           ignore-fail - (OPTIONAL) if True, failures will be ignored
                         Default is False
           progress - (OPTIONAL) When "False" will suppress progress reports
                         Default is True
    """

    REQUIRED_OPTIONS = ['account', 'container']

    def sources(self, options):
        self.pull(options)


    def pull(self, options):
        class DownloadThread(threading.Thread):
            def _progressReport(innerself, xmitted, total):
                if self.reportProgress:
                    currenttime = datetime.datetime.utcnow()
                    delta = currenttime - innerself.reporttime
                    if delta.seconds < 2:
                        return
                    deltaXmitted = xmitted - innerself.previousamount
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
                    innerself.previousamount = xmitted
                    innerself.reporttime = currenttime
                    percent=float(xmitted)/float(total)*100.0
                    if percent > 100.0:
                        percent = 100.0
                    self.log.info("[%s:%s] Transferred %2.1f%% (%d out of %d - %2.2f%s/s)",
                        innerself.container,
                        innerself.toFilename,
                        percent, xmitted, total, rate, rateunit)

            def __init__(
                innerself,
                container,
                fromFilename,
                toFilename,
                clientParams):

                threading.Thread.__init__(innerself)
                innerself.fromFilename = fromFilename
                innerself.toFilename = toFilename
                innerself.clientParams = clientParams
                innerself.container = container
                innerself.succeeded = False
                innerself.httpstatus = None
                innerself.starttime = None
                innerself.reporttime = None
                innerself.previousamount = 0

            def run(innerself):
                innerself.starttime = datetime.datetime.utcnow()
                innerself.reporttime = innerself.starttime
                try:
                    client = SwiftProvider.getConnection(innerself.clientParams)
                    with open(innerself.toFilename, 'w') as openFile:
                        SwiftProvider.doSwiftDownload(
                            client,
                            innerself.container,
                            innerself.fromFilename,
                            openFile,
                            progress=innerself._progressReport )
                    innerself.succeeded = True
                except swiftclient.exceptions.ClientException as e:
                    os.remove(innerself.toFilename)
                    if e.http_status == 404 or e.http_status == 409:
                        self.log.exception(
                            "Download of object '%s' returned %d",
                            innerself.fromFilename,
                            e.http_status )
                        self.log.warning(
                            "Step will not fail as this file was likely but not yet removed from the container")
                        innerself.succeeded=True
                    else:
                        self.log.exception(
                            "Download of object '%s' failed" )
                    innerself.httpstatus=e.http_status
                except:
                    os.remove(innerself.toFilename)
                    self.log.exception(
                        "Download of object '%s' failed", innerself.fromFilename )
                    innerself.succeeded = False
                return innerself.succeeded

            def passed(innerself):
                return innerself.succeeded or \
                    ('ignore-fail' in options and options['ignore-fail'] == 'True')

            def httpstatus(innerself):
                if self.httpstatus is None:
                    return 200
                else:
                    return self.httpstatus

        self.reportProgress = True
        if 'progress' in options:
            self.reportProgress = options['progress'] == "True"
        ignorefail = 'ignore-fail' in options and options['ignore-fail'] == 'True'
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], "pull")
        client = SwiftProvider.getConnection(clientParams)
        filematchers = ['*']
        if 'files' in options:
            filematchers = ','.join(options['files'].split('\n')).split(',')

        try:
            targetedObjects = SwiftProvider.getContainerListing(
                client,
                options['container'],
                filematchers,
                'latest-only' in options and options['latest-only'] == 'True' )
        except Exception as e:
            self.log.exception("Pull of the container failed")
            if not ignorefail:
                raise e
            else:
                self.log.passed()
                return False
        self.log.devdebug("targeted objects: %s", str(targetedObjects))

        targetPath = self.engine.resultsDir
        if 'result-dir' in options:
            targetPath = options['result-dir']

        threads = []

        for filename, (data, _) in targetedObjects.iteritems():
            targetFile = os.path.join(
                targetPath,
                filename)

            #Does the path exist?
            if os.path.exists(targetFile):
                #Yes, get the etag for the object
                eTag = data['hash']

                #get the md5 for the local file if there is one
                md5 = None
                with open(targetFile) as openFile:
                    md5 = self._fileMD5(openFile)
                if md5 == eTag:
                    self.log.info("'%s' is already up-to-date, not redownloading", targetFile)
                    continue

            self._ensureDirectoryExists(targetFile)

            threads.append(
                DownloadThread(
                    options['container'],
                    filename,
                    targetFile,
                    clientParams ) )
            threads[-1].start()

        for thread in threads:
            thread.join()
            if not thread.passed() and not ignorefail:
                self.log.failed()
                return False
        self.log.passed()
        return True
