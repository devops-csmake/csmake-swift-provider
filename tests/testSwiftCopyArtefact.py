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
"""SwiftCopyArtefact: server-side copy (X-Copy-From) between containers.

The swift connection and csmake engine are mocked.  Each object is copied
by its own real worker thread (production behaviour); failures are scripted
on the fake connection and the clock is pinned.
"""
import threading
import unittest
import unittest.mock

from . import swiftsupport

swiftsupport.setup()
copyModule = swiftsupport.loadModule('SwiftCopyArtefact')
SwiftCopyArtefact = copyModule.SwiftCopyArtefact
ClientException = swiftsupport.swiftclientClientException()

NON_ASCII = 'r\N{LATIN SMALL LETTER E WITH ACUTE}sum\N{LATIN SMALL LETTER E WITH ACUTE}.txt'


class CopyTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.engine = swiftsupport.FakeEngine()
        self.module = swiftsupport.makeModule(SwiftCopyArtefact, self.engine)

    def push(self, **options):
        options.setdefault('account', 'acct')
        options.setdefault('container', 'to')
        options.setdefault('from-container', 'from')
        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(
                    copyModule, 'time', swiftsupport.fixedTime(1234.5)):
            return self.module.push(options)

    def copied(self):
        """(to-container, object) for every put_object, sorted (the copies
        run on concurrent threads, so their order is not fixed)."""
        return sorted(a[:2] for a, _ in self.fake.callsTo('put_object'))


class TestPush(CopyTestCase):
    def setUp(self):
        CopyTestCase.setUp(self)
        for name in ('a.bin', 'b.bin', 'c.txt'):
            self.fake.addObject('from', name, b'payload')
        self.fake.addContainer('to')

    def test_push_copies_every_object_server_side(self):
        self.assertTrue(self.push())

        self.assertEqual(
            [('to', 'a.bin'), ('to', 'b.bin'), ('to', 'c.txt')], self.copied())
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_push_copy_request_carries_source_createtime_and_default_expiry(self):
        self.push()

        calls = dict((a[1], (a, k)) for a, k in self.fake.callsTo('put_object'))
        args, kwargs = calls['a.bin']
        self.assertEqual(('to', 'a.bin', None), args)
        self.assertEqual({
            'X-Copy-From': 'from/a.bin',
            'X-Object-Meta-CreateTime': '1234.5',
            'X-Delete-At': 9999999999}, kwargs['headers'])
        self.assertEqual({}, kwargs['response_dict'])

    def test_push_objects_option_limits_the_copy(self):
        self.push(objects='a*\nc.txt')

        self.assertEqual([('to', 'a.bin'), ('to', 'c.txt')], self.copied())

    def test_push_objects_option_accepts_comma_separated_patterns(self):
        self.push(objects='b.bin,c.*')

        self.assertEqual([('to', 'b.bin'), ('to', 'c.txt')], self.copied())

    def test_push_latest_only_copies_newest_match_per_pattern(self):
        fake = self.fake = swiftsupport.FakeSwift()
        fake.addObject('from', 'rel-1', b'', **{'x-object-meta-createtime': '100.0'})
        fake.addObject('from', 'rel-2', b'', **{'x-object-meta-createtime': '200.0'})

        self.push(objects='rel-*', **{'latest-only': 'True'})

        self.assertEqual([('to', 'rel-2')], self.copied())

    def test_push_non_ascii_object_names_are_copied_verbatim(self):
        self.fake.addObject('from', NON_ASCII, b'x')

        self.push(objects=NON_ASCII)

        (args, kwargs), = self.fake.callsTo('put_object')
        self.assertEqual(NON_ASCII, args[1])
        self.assertEqual('from/' + NON_ASCII, kwargs['headers']['X-Copy-From'])

    def test_push_empty_source_container_copies_nothing_and_passes(self):
        self.fake = swiftsupport.FakeSwift()
        self.fake.addContainer('from')

        self.assertTrue(self.push())

        self.assertEqual([], self.fake.callsTo('put_object'))
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_push_no_matching_objects_copies_nothing(self):
        self.assertTrue(self.push(objects='zzz*'))

        self.assertEqual([], self.fake.callsTo('put_object'))

    def test_push_missing_source_container_raises_404_and_copies_nothing(self):
        self.fake = swiftsupport.FakeSwift()

        with self.assertRaises(ClientException) as ctx:
            self.push()

        self.assertEqual(404, ctx.exception.http_status)
        self.assertEqual([], self.fake.callsTo('put_object'))

    def test_push_failed_account_step_raises_before_any_swift_call(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.push()

        self.assertEqual([], self.fake.calls)

    def test_push_object_gone_404_is_tolerated_with_a_warning(self):
        self.fake.failOn('put_object', 404, name='b.bin')

        self.assertTrue(self.push())

        warnings = self.module.log.messages('warning')
        self.assertIn("Copy of object 'from/b.bin' returned: 404", warnings)
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_push_object_conflict_409_is_tolerated_with_a_warning(self):
        self.fake.failOn('put_object', 409, name='b.bin')

        self.assertTrue(self.push())

        self.assertIn("Copy of object 'from/b.bin' returned: 409",
                      self.module.log.messages('warning'))

    def test_push_server_error_fails_the_step(self):
        self.fake.failOn('put_object', 500, name='b.bin')

        self.assertFalse(self.push())

        self.assertIn('failed', self.module.log.names())
        self.assertNotIn('passed', self.module.log.names())
        self.assertIn('exception', self.module.log.names())

    def test_push_forbidden_fails_the_step(self):
        self.fake.failOn('put_object', 403)

        self.assertFalse(self.push())

    def test_push_other_objects_are_still_copied_when_one_fails(self):
        self.fake.failOn('put_object', 500, name='a.bin')

        self.push()

        self.assertEqual(
            [('to', 'a.bin'), ('to', 'b.bin'), ('to', 'c.txt')], self.copied())

    def test_push_unexpected_exception_in_a_copy_fails_the_step(self):
        self.fake.failOn('put_object', name='b.bin',
                         exc=ConnectionResetError('connection dropped'))

        with unittest.mock.patch.object(threading, 'excepthook'):
            result = self.push()

        self.assertFalse(result)
        self.assertIn('failed', self.module.log.names())


class TestPrep(CopyTestCase):
    def prep(self, **options):
        options.setdefault('account', 'acct')
        options.setdefault('container', 'to')
        with swiftsupport.patchConnection(self.fake):
            return self.module.prep(options)

    def test_prep_creates_missing_destination_container(self):
        self.assertTrue(self.prep())

        self.assertEqual([(('to', {}), {})], self.fake.callsTo('put_container'))
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_prep_leaves_existing_destination_container_alone(self):
        self.fake.addContainer('to')

        self.prep()

        self.assertEqual(['get_container'], self.fake.methodsCalled())

    def test_prep_access_grants_read_to_each_reader(self):
        self.engine.accounts['r1'] = ({}, {'account': 'p1', 'user': 'u1'})
        self.engine.accounts['r2'] = ({}, {'account': 'p2', 'user': 'u2'})

        self.prep(access='r1,r2')

        self.assertEqual(
            [(('to', {'X-Container-Read': 'p1:u1,p2:u2'}), {})],
            self.fake.callsTo('post_container'))

    def test_prep_failed_account_step_raises_and_touches_nothing(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaises(ValueError):
            self.prep()

        self.assertEqual([], self.fake.calls)

    def test_prep_container_create_forbidden_propagates(self):
        self.fake.failOn('put_container', 403)

        with self.assertRaises(ClientException):
            self.prep()


if __name__ == '__main__':
    unittest.main()
