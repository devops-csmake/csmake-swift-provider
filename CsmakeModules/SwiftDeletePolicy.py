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
import datetime

class SwiftDeletePolicy(CsmakeModule):
    """Library: csmake-swift-provider
       Purpose: Set deletion strategy and enforce it.
       Phase:
           push, enforce_policy - Will execute the delete policy
       Options:
           account - SwiftAccount section id to use to authorize the transfer
                     (because this manages container lifecycle,
                      an admin account must be used)
           containers - Container to enforce delete policy
                     Posix file wildcards like '*' and '?' can be used.
           expires - Specify the amount of time before
                        the artefact(s) given in the list should expire
                        after the object's x-timestamp time.
           leave - (OPTIONAL) Leaves the latest # specified
                              Regardless of time.
           objects - (OPTIONAL) The objects to check/delete
                     (either newline or comma delimited) from the container.  
                     Posix file wildcards like '*' and '?' can be used.
                     Default is '*'"""

    REQUIRED_OPTIONS = ['account', 'containers', 'expires']

    def enforce_policy(self, options):
        return self.push(options)

    def push(self, options):

        #Get the current time
        utcnow = datetime.datetime.utcnow()

        #Get the timeout policy
        expires = datetime.timedelta()
        if 'expires' in options:
            expires = SwiftProvider.timeDeltaDisgronifier(options['expires'])

        self.log.devdebug("UTC: %s, expires: %s", utcnow, expires)

        #Execute the account section to get the account info
        (clientParams, account) = SwiftProvider.getAccount(self.engine, options['account'], 'push')
        client = SwiftProvider.getConnection(clientParams)

        containerMatcher = ','.join(options['containers'].split('\n')).split(',')
        objectMatcher = '*'
        if 'objects' in options:
            objectMatcher = ','.join(options['objects'].split('\n')).split(',')

        targetedContainers = SwiftProvider.getAccountListing(
            client,
            containerMatcher)

        for ctrname, container in targetedContainers.iteritems():
            targetedObjects = SwiftProvider.getContainerListing(
                client,
                ctrname,
                objectMatcher,
                details=True )

            objectlist = targetedObjects.keys()
            detaillist = targetedObjects.values()

            if 'leave' in options:
                leave = int(options['leave'])
                leave = min(leave,len(targetedObjects))
                sortedvals = sorted(
                    targetedObjects.values(), 
                    key=lambda k:k[0]['x-object-meta-createtime'] )
                leaves = sortedvals[-leave:]
                sortedvals = sortedvals[:-leave]
                leaveobjects = []
                leavedetail = []
                for val in leaves:
                    leaveobjects.append(val[0]['name'])
                    leavedetail.append(val)
                objectlist = []
                detaillist = []
                for val in sortedvals:
                    objectlist.append(val[0]['name'])
                    detaillist.append(val)

                leaveObjects = zip(leaveobjects, leavedetail)
                for objectTarget, (details, filterer) in leaveObjects:
                    if 'x-delete-at' in details:
                        if details['x-delete-at'] == '9999999999':
                            continue
                        #I want to delete the "delete-at", but it doesn't
                        #  appear a way to do that
                        headers = SwiftProvider.getMetadataFromDict(details)
                        headers['x-delete-at'] = "9999999999"
                        client.post_object(
                            ctrname, 
                            objectTarget, 
                            headers=headers )
                        self.log.debug("%s/%s: Object preserved by policy", ctrname, objectTarget)

            targetedObjects = zip(objectlist, detaillist)
               
            self.log.devdebug("In Container: %s", ctrname)

            for objectTarget, (details, filterer) in targetedObjects:
                #Check to see if x-object-meta-createtime exists
                timestamp = datetime.datetime.utcfromtimestamp(
                    float(details['x-object-meta-createtime']) )

                utcexpire = timestamp + expires

                #Is the object expired according to this policy?
                if utcexpire < utcnow:
                    #Yes. Delete it.
                    client.delete_object(ctrname, objectTarget)
                    self.log.debug("%s/%s: Object deleted - aged out", ctrname, objectTarget)
                    continue

                #Does the object already have an expiration set?
                if 'x-delete-at' in details:
                    #Yes.  Check the time, is it according to this policy?
                    deltime = datetime.datetime.utcfromtimestamp(
                        float(details['x-delete-at']))
                    if utcexpire - deltime <= datetime.timedelta(minutes=1) \
                       or deltime - utcexpire <= datetime.timedelta(minutes=1):
                        #Yes.  The world is as it should be.
                        #NOTE: A minute should give plenty of time to account
                        #      for losses and, really, what's one minute
                        #      for archival?  The object won't be cleaned
                        #      out off the disk until the "expirer" service
                        #      runs and takes out the trash.
                        #      The goal is to not have to communicate for
                        #      an object that already meets the policy +/-
                        self.log.debug("%s/%s: File expiry follows policy", ctrname,objectTarget)
                        continue

                #Set the policy.
                secondsToExpire = str(int((utcexpire-utcnow).total_seconds()))
                headers = SwiftProvider.getMetadataFromDict(details)
                headers['x-delete-after'] = secondsToExpire
                client.post_object(
                    ctrname, 
                    objectTarget, 
                    headers=headers )
                self.log.debug("%s/%s: File will expire after %s seconds", ctrname, objectTarget, secondsToExpire)
        self.log.passed()
        return True
