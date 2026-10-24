# <copyright>
# (c) Copyright 2026 Autumn Patterson
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
"""SwiftProvider helpers whose dict handling changed for Python 3.

iteritems() -> items(), and values()/keys() are views rather than lists.
"""
import unittest

from . import swiftsupport

swiftsupport.setup()
from CsmakeSwiftProvider.SwiftProvider import SwiftProvider

CREATETIME = 'x-object-meta-createtime'


class TestSwiftProvider(unittest.TestCase):
    def testFilenameMatchingLatestOnlyKeepsNewestPerMatcher(self):
        objects = [
            {'name': 'app-1', CREATETIME: 100.0},
            {'name': 'app-2', CREATETIME: 200.0},
            {'name': 'app-3', CREATETIME: 150.0},
            {'name': 'other', CREATETIME: 1.0},
        ]

        newestOnly = SwiftProvider.filenameMatching(
            ['app-*'], True, objects, CREATETIME)
        self.assertEqual({'app-2'}, set(newestOnly))
        self.assertEqual((objects[1], ['app-*']), newestOnly['app-2'])

        # an object also matched by a second matcher survives under it
        both = SwiftProvider.filenameMatching(
            ['app-*', 'app-1'], True, objects, CREATETIME)
        self.assertEqual({'app-2', 'app-1'}, set(both))
        self.assertEqual(['app-1'], both['app-1'][1])

    def testAddDetailsDropsObjectsThatVanishedFromDictAndList(self):
        fake = swiftsupport.FakeSwift()
        fake.addObject('c', 'kept', b'1')
        fake.addObject('c', 'vanished', b'2')
        listing = fake.get_container('c')[1]
        del fake.containers['c']['objects']['vanished']   # head => 404

        byName = {o['name']: dict(o) for o in listing}
        SwiftProvider.addDetailsToContainerListing(fake, 'c', byName)
        self.assertEqual(['kept'], list(byName))
        self.assertEqual('1.0', byName['kept'][CREATETIME])
        self.assertEqual('1', byName['kept']['content-length'])

        asList = [{'name': 'kept'}, {'name': 'vanished'}]
        SwiftProvider.addDetailsToContainerListing(fake, 'c', asList)
        self.assertEqual(['kept'], [o['name'] for o in asList])

    def testContainerListingWithDetailsAndMetadataFilters(self):
        fake = swiftsupport.FakeSwift()
        fake.addObject('c', 'a.tar', b'1', **{
            CREATETIME: '5.0', 'x-object-meta-owner': 'ci',
            'etag': 'abc'})
        fake.addObject('c', 'b.txt', b'2')

        result = SwiftProvider.getContainerListing(
            fake, 'c', ['*.tar'], details=True)

        self.assertEqual(['a.tar'], list(result))
        details, matchers = result['a.tar']
        self.assertEqual(['*.tar'], matchers)
        self.assertEqual('5.0', details[CREATETIME])
        self.assertEqual(
            {CREATETIME: '5.0', 'x-object-meta-owner': 'ci'},
            SwiftProvider.getMetadataFromDict(details))
        self.assertEqual(
            {'x-container-meta-a': '1'},
            SwiftProvider.getMetadataFromContainerDict(
                {'x-container-meta-a': '1', 'x-timestamp': '2'}))


if __name__ == '__main__':
    unittest.main()
