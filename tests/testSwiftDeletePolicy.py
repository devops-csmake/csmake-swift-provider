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
"""SwiftDeletePolicy: expiry policy over an account's containers/objects.

The module walks account -> containers -> objects with dict.items()/keys()/
values() and pairs object names with their detail tuples via zip().  Under
Python 3 those are views/iterators and iteritems() is gone, so these tests
check the policy outcome end to end -- each object must be acted on according
to its *own* age -- against an in-memory swift.
"""
import time
import unittest
import warnings

from . import swiftsupport

swiftsupport.setup()
SwiftDeletePolicy = swiftsupport.loadModule('SwiftDeletePolicy').SwiftDeletePolicy

HOUR = 3600.0
DAY = 24 * HOUR


class TestSwiftDeletePolicy(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.module = swiftsupport.makeModule(
            SwiftDeletePolicy, swiftsupport.FakeEngine())
        self.now = time.time()

    def add(self, name, ageSeconds, **headers):
        self.fake.addObject(
            'builds', name, b'x',
            **{'x-object-meta-createtime': str(self.now - ageSeconds),
               'x-object-meta-note': 'note-for-' + name},
            **headers)

    def enforce(self, **options):
        options.update({'account': 'acct', 'containers': 'builds'})
        with swiftsupport.patchConnection(self.fake), \
                warnings.catch_warnings():
            # the module uses datetime.utcnow(), deprecated since 3.12
            warnings.filterwarnings(
                'ignore', message='datetime.datetime.utc',
                category=DeprecationWarning)
            return self.module.push(options)

    def testEachObjectIsJudgedByItsOwnAge(self):
        self.add('old.tar', 10 * DAY)
        self.add('fresh.tar', 1 * HOUR)
        self.add('compliant.tar', 2 * HOUR,
                 **{'x-delete-at': str(int(self.now - 2 * HOUR + DAY))})

        self.assertTrue(self.enforce(expires='1d'))

        # older than the 1d policy: deleted, and only that one
        self.assertEqual(
            [(('builds', 'old.tar'), {})], self.fake.callsTo('delete_object'))
        # no expiry yet: stamped with the remaining ~23h, keeping its metadata
        posts = self.fake.callsTo('post_object')
        self.assertEqual(1, len(posts))
        (container, name), kwargs = posts[0]
        self.assertEqual(('builds', 'fresh.tar'), (container, name))
        self.assertEqual('note-for-fresh.tar',
                         kwargs['headers']['x-object-meta-note'])
        self.assertTrue(
            82700 <= int(kwargs['headers']['x-delete-after']) <= 82800,
            kwargs['headers']['x-delete-after'])
        # compliant.tar already follows the policy: left alone
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def testLeaveKeepsNewestObjectsAndPreservesTheirExpiry(self):
        self.add('a.tar', 30 * DAY)
        self.add('b.tar', 20 * DAY)
        self.add('c.tar', 10 * DAY, **{'x-delete-at': '1234567890'})

        self.assertTrue(self.enforce(expires='1d', leave='1'))

        deleted = [args[1] for args, _ in self.fake.callsTo('delete_object')]
        self.assertEqual(['a.tar', 'b.tar'], deleted)
        # the newest is exempt from deletion and its x-delete-at is pushed out
        posts = self.fake.callsTo('post_object')
        self.assertEqual(1, len(posts))
        (container, name), kwargs = posts[0]
        self.assertEqual(('builds', 'c.tar'), (container, name))
        self.assertEqual('9999999999', kwargs['headers']['x-delete-at'])
        self.assertEqual('note-for-c.tar',
                         kwargs['headers']['x-object-meta-note'])


if __name__ == '__main__':
    unittest.main()
