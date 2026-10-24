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
"""SwiftCleanupContainers: remove dangling object links and empty containers.

Walks account -> containers -> objects with dict.items() (iteritems() is gone
in Python 3), deleting links whose x-object-manifest target no longer exists
and then any container left empty.
"""
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftCleanupContainers = swiftsupport.loadModule(
    'SwiftCleanupContainers').SwiftCleanupContainers


class TestSwiftCleanupContainers(unittest.TestCase):
    def testDanglingLinksAndEmptiedContainersAreRemoved(self):
        fake = swiftsupport.FakeSwift()
        # 'links' holds only a link to something that no longer exists
        fake.addObject('links', 'dangling.bin', b'',
                       **{'x-object-manifest': 'gone/dangling.bin'})
        fake.addObject('gone', 'unrelated.bin', b'x')
        # 'keep' holds a live link, a malformed link and a plain object
        fake.addObject('keep', 'live.bin', b'',
                       **{'x-object-manifest': 'data/real.bin'})
        fake.addObject('keep', 'malformed.bin', b'',
                       **{'x-object-manifest': 'no-container-delimiter'})
        fake.addObject('keep', 'plain.txt', b'text')
        fake.addObject('data', 'real.bin', b'payload')
        module = swiftsupport.makeModule(
            SwiftCleanupContainers, swiftsupport.FakeEngine())

        with swiftsupport.patchConnection(fake):
            self.assertTrue(module.push(
                {'account': 'acct', 'containers': 'links,keep'}))

        self.assertEqual(
            [(('links', 'dangling.bin'), {})], fake.callsTo('delete_object'))
        self.assertEqual([(('links',), {})], fake.callsTo('delete_container'))
        self.assertEqual({'keep', 'gone', 'data'}, set(fake.containers))
        self.assertEqual(
            {'live.bin', 'malformed.bin', 'plain.txt'},
            set(fake.containers['keep']['objects']))
        self.assertEqual(['passed'], module.log.names()[-1:])


if __name__ == '__main__':
    unittest.main()
