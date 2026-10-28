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
to its *own* age.  The swift connection and csmake engine are mocked and the
clock is pinned, so ages and x-delete-after values are exact.
"""
import datetime
import types
import unittest
import unittest.mock
import warnings

from . import swiftsupport

swiftsupport.setup()
deleteModule = swiftsupport.loadModule('SwiftDeletePolicy')
SwiftDeletePolicy = deleteModule.SwiftDeletePolicy
ClientException = swiftsupport.swiftclientClientException()

HOUR = 3600.0
DAY = 24 * HOUR
NOW = 1700000000.0                                  # epoch seconds
UTCNOW = datetime.datetime(2023, 11, 14, 22, 13, 20)  # the same instant, naive UTC


class FrozenDatetime(datetime.datetime):
    @classmethod
    def utcnow(cls):
        return UTCNOW


FROZEN_CLOCK = types.SimpleNamespace(
    datetime=FrozenDatetime, timedelta=datetime.timedelta)


class PolicyTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.engine = swiftsupport.FakeEngine()
        self.module = swiftsupport.makeModule(SwiftDeletePolicy, self.engine)

    def add(self, name, ageSeconds, container='builds', **headers):
        self.fake.addObject(
            container, name, b'x',
            **{'x-object-meta-createtime': str(NOW - ageSeconds),
               'x-object-meta-note': 'note-for-' + name},
            **headers)

    def enforce(self, **options):
        options.setdefault('account', 'acct')
        options.setdefault('containers', 'builds')
        options.setdefault('expires', '1d')
        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(deleteModule, 'datetime', FROZEN_CLOCK), \
                warnings.catch_warnings():
            # utcfromtimestamp() is deprecated since Python 3.12
            warnings.filterwarnings(
                'ignore', message='datetime.datetime.utc',
                category=DeprecationWarning)
            return self.module.push(options)

    def deleted(self):
        return [a for a, _ in self.fake.callsTo('delete_object')]

    def posted(self):
        return [(a, k['headers']) for a, k in self.fake.callsTo('post_object')]


class TestPolicy(PolicyTestCase):
    def test_enforce_deletes_objects_older_than_expiry(self):
        self.add('old.tar', 10 * DAY)
        self.add('fresh.tar', 1 * HOUR)

        self.assertTrue(self.enforce())

        self.assertEqual([('builds', 'old.tar')], self.deleted())

    def test_enforce_stamps_delete_after_with_the_remaining_lifetime(self):
        self.add('fresh.tar', 1 * HOUR)

        self.enforce()

        self.assertEqual(
            [(('builds', 'fresh.tar'),
              {'x-object-meta-createtime': str(NOW - HOUR),
               'x-object-meta-note': 'note-for-fresh.tar',
               'x-delete-after': '82800'})],      # 24h - 1h
            self.posted())

    def test_enforce_leaves_unexpired_object_that_already_follows_policy(self):
        self.add('ok.tar', 2 * HOUR,
                 **{'x-delete-at': str(int(NOW - 2 * HOUR + DAY))})

        self.enforce()

        self.assertEqual([], self.deleted())
        self.assertEqual([], self.posted())

    def test_enforce_judges_each_object_by_its_own_age(self):
        self.add('old.tar', 10 * DAY)
        self.add('fresh.tar', 1 * HOUR)
        self.add('older.tar', 3 * DAY)
        self.add('ok.tar', 2 * HOUR,
                 **{'x-delete-at': str(int(NOW - 2 * HOUR + DAY))})

        self.enforce()

        self.assertEqual(
            [('builds', 'old.tar'), ('builds', 'older.tar')], sorted(self.deleted()))
        self.assertEqual([('builds', 'fresh.tar')], [a for a, _ in self.posted()])

    def test_enforce_uses_x_timestamp_when_createtime_metadata_is_missing(self):
        self.fake.addObject('builds', 'legacy.tar', b'x',
                            **{'x-timestamp': str(NOW - 10 * DAY)})

        self.enforce()

        self.assertEqual([('builds', 'legacy.tar')], self.deleted())

    def test_enforce_objects_option_restricts_the_objects_considered(self):
        self.add('old.tar', 10 * DAY)
        self.add('old.txt', 10 * DAY)
        self.add('old.log', 10 * DAY)

        self.enforce(objects='*.tar\n*.log')

        self.assertEqual(
            [('builds', 'old.log'), ('builds', 'old.tar')], sorted(self.deleted()))

    def test_enforce_containers_pattern_covers_every_matching_container(self):
        self.add('old.tar', 10 * DAY, container='ci-a')
        self.add('old.tar', 10 * DAY, container='ci-b')
        self.add('old.tar', 10 * DAY, container='other')

        self.enforce(containers='ci-*')

        self.assertEqual(
            [('ci-a', 'old.tar'), ('ci-b', 'old.tar')], sorted(self.deleted()))

    def test_enforce_empty_container_passes_without_changes(self):
        self.fake.addContainer('builds')

        self.assertTrue(self.enforce())

        self.assertEqual([], self.deleted())
        self.assertEqual([], self.posted())
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_enforce_policy_phase_runs_the_same_policy(self):
        self.add('old.tar', 10 * DAY)

        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(deleteModule, 'datetime', FROZEN_CLOCK), \
                warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            self.module.enforce_policy(
                {'account': 'acct', 'containers': 'builds', 'expires': '1d'})

        self.assertEqual([('builds', 'old.tar')], self.deleted())


class TestLeave(PolicyTestCase):
    def setUp(self):
        PolicyTestCase.setUp(self)
        self.add('a.tar', 30 * DAY)
        self.add('b.tar', 20 * DAY)

    def test_leave_deletes_expired_objects_except_the_newest(self):
        self.add('c.tar', 10 * DAY)

        self.enforce(leave='1')

        self.assertEqual(
            [('builds', 'a.tar'), ('builds', 'b.tar')], self.deleted())

    def test_leave_pushes_out_the_delete_at_of_each_preserved_object(self):
        self.add('c.tar', 10 * DAY, **{'x-delete-at': '1234567890'})

        self.enforce(leave='1')

        self.assertEqual(
            [(('builds', 'c.tar'),
              {'x-object-meta-createtime': str(NOW - 10 * DAY),
               'x-object-meta-note': 'note-for-c.tar',
               'x-delete-at': '9999999999'})],
            self.posted())

    def test_leave_skips_preserved_object_already_set_to_never_expire(self):
        self.add('c.tar', 10 * DAY, **{'x-delete-at': '9999999999'})

        self.enforce(leave='1')

        self.assertEqual([], self.posted())

    def test_leave_needs_no_update_for_preserved_object_without_delete_at(self):
        self.add('c.tar', 10 * DAY)

        self.enforce(leave='1')

        self.assertEqual([], self.posted())
        self.assertNotIn(('builds', 'c.tar'), self.deleted())

    def test_leave_larger_than_the_object_count_deletes_nothing(self):
        self.enforce(leave='5')

        self.assertEqual([], self.deleted())

    def test_leave_two_keeps_the_two_newest(self):
        self.add('c.tar', 10 * DAY)

        self.enforce(leave='2')

        self.assertEqual([('builds', 'a.tar')], self.deleted())


class TestFailures(PolicyTestCase):
    def test_enforce_failed_account_step_raises_before_any_swift_call(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.enforce()

        self.assertEqual([], self.fake.calls)

    def test_enforce_account_listing_error_propagates(self):
        self.fake.failOn('get_account', 401)

        with self.assertRaises(ClientException) as ctx:
            self.enforce()

        self.assertEqual(401, ctx.exception.http_status)

    def test_enforce_container_listing_error_propagates(self):
        self.add('old.tar', 10 * DAY)
        self.fake.failOn('get_container', 500, container='builds')

        with self.assertRaises(ClientException):
            self.enforce()

        self.assertEqual([], self.deleted())

    def test_enforce_delete_error_propagates_and_step_is_not_passed(self):
        self.add('old.tar', 10 * DAY)
        self.fake.failOn('delete_object', 500)

        with self.assertRaises(ClientException):
            self.enforce()

        self.assertNotIn('passed', self.module.log.names())

    def test_enforce_post_error_propagates(self):
        self.add('fresh.tar', 1 * HOUR)
        self.fake.failOn('post_object', 403)

        with self.assertRaises(ClientException):
            self.enforce()

    def test_enforce_unparseable_expires_raises_before_touching_swift(self):
        with self.assertRaises(KeyError):
            self.enforce(expires='3y')

        self.assertEqual([], self.fake.calls)


if __name__ == '__main__':
    unittest.main()
