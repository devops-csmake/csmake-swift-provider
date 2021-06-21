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
import swiftclient
import swiftclient.exceptions
import fnmatch
import datetime

class SwiftProvider:
    """Support library for working with the swiftclient API"""

    _timeDeltaMapping = {
       'w':'weeks',
       'd':'days',
       'h':'hours',
       'm':'minutes',
       's':'seconds' }

    @classmethod
    def timeDeltaDisgronifier(clazz, timeString):
        timeparts = timeString.split()
        timedict = {}
        for part in timeparts:
            timetype = part[-1]
            time = part[:-1]
            timedict[clazz._timeDeltaMapping[timetype]] = int(time)
        return datetime.timedelta(**timedict)

    @staticmethod
    def getAccount(engine, account, phase):
        result = engine.launchStep(account, phase)
        if result is None or not result._didPass():
            raise ValueError("%s step failed" % account)
        return result._getReturnValue(phase)

    @staticmethod
    def getContainerAndFile(fromfile, container):
        if '/' in container:
            return tuple(container.split('/', 1))
        else:
            return (container, fromfile)

    @staticmethod
    def getConnection(connectionParams):
        client = swiftclient.client.Connection(**connectionParams)
        if client is None:
            raise ValueError("Could not make a swift connection: %s" % str(connectionParams))
        return client

    @staticmethod
    def ensureContainer(client, container):
        result = None
        try:
            result = client.get_container(container)
        except:
            result = {}
            client.put_container(container, result)
        if result is None:
            result = {}
            client.put_container(container, result)
        return result


    @staticmethod
    def setContainerAccounts(engine, access, client, container, readers, phase):
        delim = ""
        accessSteps = ','.join(readers.split('\n')).split(',')
        readerList = []
        for step in accessSteps:
            step = step.strip()
            _, acct = SwiftProvider.getAccount(engine, step, phase)
            readerList.append("%s%s:%s" % (
                delim,
                acct['account'],
                acct['user'] ) )
            delim = ','
        headers = None
        if len(readers) > 0:
            headers = {}
            headers['X-Container-%s' % access] = ''.join(readerList)

            result = {}
            client.post_container(container, headers, response_dict=result)
            return result
        else:
            return None

    @staticmethod
    def doSwiftDownload(client, container, objectName, openFile, headers=None, progress=None):
        responseDict = {}
        length=client.head_object(container, objectName)['content-length']
        try:
            length = int(length)
        except:
            length = -1
        chunksize = 1024000
        resultHeaders, chunkIterator = client.get_object(
            container,
            objectName,
            resp_chunk_size=chunksize,
            response_dict=responseDict,
            headers=headers )
        totalTransmitted = 0
        for chunk in chunkIterator:
            openFile.write(chunk)
            totalTransmitted += chunksize
            try:
                if progress is not None and length != -1:
                    progress(totalTransmitted, length)
            except:
                pass
        return (responseDict, resultHeaders)

    @staticmethod
    def filenameMatching(matchers, latestOnly, objects, timekey):
        targetedObjects = {}
        targetedFilematches = {}
        filematchers = [ x.strip() for x in matchers ]
        for objectdata in objects:
            for matcher in filematchers:
                objectname = objectdata['name']
                if fnmatch.fnmatch(objectname, matcher):
                    if objectname not in targetedObjects:
                        targetedObjects[objectname] = (objectdata, [])
                    targetedObjects[objectname][1].append(matcher)
                    if matcher not in targetedFilematches:
                        targetedFilematches[matcher] = []
                    targetedFilematches[matcher].append(objectdata)

        if latestOnly:
            for key, value in targetedFilematches.iteritems():
                if len(value) > 1:
                    sortedObjects = sorted(value, key=lambda k: k[timekey])
                    for removal in sortedObjects[:-1]:
                        objectname = removal['name']
                        targetedObjects[objectname][1].remove(key)
                        if len(targetedObjects[objectname][1]) == 0:
                            del targetedObjects[objectname]

        return targetedObjects

    @staticmethod
    def addDetailsToAccountListing(client, containers):
        if type(containers) is dict:
            containers = containers.values()
        for container in containers:
            if type(container) is tuple:
                container = container[0]
            container.update(client.head_container(container['name']))
            if 'x-container-meta-createtime' not in container:
                container['x-container-meta-createtime'] = \
                    container['x-timestamp']

    @staticmethod
    def addDetailsToContainerListing(client, container, objects):
        removed = []
        origobjects = objects
        if type(objects) is dict:
            objects = objects.values()
        for myobject in objects:
            if type(myobject) is tuple:
                myobject = myobject[0]
            try:
                myobject.update(client.head_object(container, myobject['name']))
                if 'x-object-meta-createtime' not in myobject:
                    myobject['x-object-meta-createtime'] = \
                        myobject['x-timestamp']
            except swiftclient.exceptions.ClientException as e:
                if e.http_status == 404 or e.http_status == 409 or e.http_status == 403:
                    removed.append(myobject)
                else:
                    raise e
        if type(origobjects) is dict:
            for myobject in removed:
                actualkey = None
                for key, value in origobjects.iteritems():
                    if value is myobject:
                        actualkey = key
                        break
                if actualkey is not None:
                    del origobjects[actualkey]
        else:
            for myobject in removed:
                origobjects.remove(myobject)

    @staticmethod
    def getAccountListing(client, matchers=['*'], latestOnly=False, details=False):
        _, containers = client.get_account()
        if latestOnly:
            SwiftProvider.addDetailsToAccountListing(client, containers)
        result = SwiftProvider.filenameMatching(
            matchers,
            latestOnly,
            containers,
            'x-container-meta-createtime')
        if details and not latestOnly:
            SwiftProvider.addDetailsToAccontListing(client, result)
        return result

    @staticmethod
    def getContainerListing(client, container, filematchers=['*'], latestOnly=False, details=False):
        _, objects = client.get_container(container)
        if latestOnly:
            SwiftProvider.addDetailsToContainerListing(
                client, container, objects)
        result = SwiftProvider.filenameMatching(
            filematchers,
            latestOnly,
            objects,
            'x-object-meta-createtime' )
        if details and not latestOnly:
            SwiftProvider.addDetailsToContainerListing(
                client, container, result )
        return result

    @staticmethod
    def getMetadataFromContainerDict(swiftdict):
        results = {}
        for key, value in swiftdict.iteritems():
            if key.startswith('x-container-meta'):
                results[key] = value
        return results

    @staticmethod
    def getMetadataFromDict(swiftdict):
        result = {}
        for key, value in swiftdict.iteritems():
            if key.startswith('x-object-meta'):
                result[key] = value
        return result
