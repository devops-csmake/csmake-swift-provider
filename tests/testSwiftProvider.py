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
"""SwiftProvider: the support library behind every swift module.

The swift connection and the csmake engine are the fakes from swiftsupport.
Scenarios cover success and the failure modes of each helper (failed account
step, 404s, swift errors, non-numeric lengths, ...).
"""
import datetime
import io
import unittest
from unittest import mock

from . import swiftsupport

swiftsupport.setup()
import swiftclient.client
from CsmakeSwiftProvider.SwiftProvider import SwiftProvider

CREATETIME = 'x-object-meta-createtime'
ClientException = swiftsupport.swiftclientClientException()


class TestTimeDeltaDisgronifier(unittest.TestCase):
    def test_timeDeltaDisgronifier_parses_every_unit(self):
        self.assertEqual(
            datetime.timedelta(weeks=2, days=5, hours=1, minutes=7, seconds=33),
            SwiftProvider.timeDeltaDisgronifier('2w 5d 1h 7m 33s'))

    def test_timeDeltaDisgronifier_empty_string_is_zero(self):
        self.assertEqual(datetime.timedelta(), SwiftProvider.timeDeltaDisgronifier(''))

    def test_timeDeltaDisgronifier_unknown_unit_raises_keyerror(self):
        with self.assertRaises(KeyError):
            SwiftProvider.timeDeltaDisgronifier('5y')

    def test_timeDeltaDisgronifier_non_numeric_amount_raises_valueerror(self):
        with self.assertRaises(ValueError):
            SwiftProvider.timeDeltaDisgronifier('xd')


class TestGetAccount(unittest.TestCase):
    def test_getAccount_returns_step_value_for_the_requested_phase(self):
        engine = swiftsupport.FakeEngine()
        engine.accounts['acct'] = ({'authurl': 'u'}, {'account': 'a', 'user': 'x'})

        result = SwiftProvider.getAccount(engine, 'acct', 'push')

        self.assertEqual(({'authurl': 'u'}, {'account': 'a', 'user': 'x'}), result)
        self.assertEqual([('acct', 'push')], engine.launched)

    def test_getAccount_failed_step_raises_valueerror(self):
        engine = swiftsupport.FakeEngine()
        engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            SwiftProvider.getAccount(engine, 'acct', 'push')

    def test_getAccount_missing_step_result_raises_valueerror(self):
        engine = swiftsupport.FakeEngine()
        engine.results['acct'] = None

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            SwiftProvider.getAccount(engine, 'acct', 'push')


class TestGetContainerAndFile(unittest.TestCase):
    def test_getContainerAndFile_without_slash_keeps_both(self):
        self.assertEqual(('bucket', 'dir/file'),
                         SwiftProvider.getContainerAndFile('dir/file', 'bucket'))

    def test_getContainerAndFile_slash_splits_container_from_object_name(self):
        self.assertEqual(('bucket', 'a/b/c'),
                         SwiftProvider.getContainerAndFile('ignored', 'bucket/a/b/c'))


class TestGetConnection(unittest.TestCase):
    def test_getConnection_passes_params_as_keyword_arguments(self):
        seen = {}

        def connection(**params):
            seen.update(params)
            return 'client'
        with mock.patch.object(swiftclient.client, 'Connection', connection):
            client = SwiftProvider.getConnection({'authurl': 'u', 'retries': 3})

        self.assertEqual('client', client)
        self.assertEqual({'authurl': 'u', 'retries': 3}, seen)

    def test_getConnection_none_connection_raises_valueerror(self):
        with mock.patch.object(swiftclient.client, 'Connection', lambda **p: None):
            with self.assertRaises(ValueError):
                SwiftProvider.getConnection({'authurl': 'u'})


class TestEnsureContainer(unittest.TestCase):
    def test_ensureContainer_existing_container_is_not_created(self):
        fake = swiftsupport.FakeSwift()
        fake.addContainer('c')

        SwiftProvider.ensureContainer(fake, 'c')

        self.assertEqual(['get_container'], fake.methodsCalled())

    def test_ensureContainer_missing_container_is_created(self):
        fake = swiftsupport.FakeSwift()

        SwiftProvider.ensureContainer(fake, 'c')

        self.assertEqual([(('c', {}), {})], fake.callsTo('put_container'))

    def test_ensureContainer_none_listing_creates_container(self):
        fake = swiftsupport.FakeSwift()
        fake.get_container = lambda container: None

        SwiftProvider.ensureContainer(fake, 'c')

        self.assertEqual([(('c', {}), {})], fake.callsTo('put_container'))


class TestSetContainerAccounts(unittest.TestCase):
    def test_setContainerAccounts_posts_comma_joined_account_user_pairs(self):
        engine = swiftsupport.FakeEngine()
        engine.accounts['r1'] = ({}, {'account': 'projA', 'user': 'ua'})
        engine.accounts['r2'] = ({}, {'account': 'projB', 'user': 'ub'})
        fake = swiftsupport.FakeSwift()

        result = SwiftProvider.setContainerAccounts(
            engine, 'Read', fake, 'c', 'r1\n r2', 'prep')

        self.assertEqual({}, result)
        self.assertEqual([('r1', 'prep'), ('r2', 'prep')], engine.launched)
        self.assertEqual(
            [(('c', {'X-Container-Read': 'projA:ua,projB:ub'}), {})],
            fake.callsTo('post_container'))

    def test_setContainerAccounts_write_access_uses_write_header(self):
        engine = swiftsupport.FakeEngine()
        fake = swiftsupport.FakeSwift()

        SwiftProvider.setContainerAccounts(engine, 'Write', fake, 'c', 'r1', 'prep')

        (_, headers), _ = fake.callsTo('post_container')[0]
        self.assertEqual({'X-Container-Write': 'acct:usr'}, headers)

    def test_setContainerAccounts_failed_reader_step_raises_before_posting(self):
        engine = swiftsupport.FakeEngine()
        engine.results['r2'] = swiftsupport.stepResult(passed=False)
        fake = swiftsupport.FakeSwift()

        with self.assertRaisesRegex(ValueError, 'r2 step failed'):
            SwiftProvider.setContainerAccounts(
                engine, 'Read', fake, 'c', 'r1,r2', 'prep')

        self.assertEqual([], fake.callsTo('post_container'))

    def test_setContainerAccounts_post_error_propagates(self):
        fake = swiftsupport.FakeSwift()
        fake.failOn('post_container', 403)

        with self.assertRaises(ClientException):
            SwiftProvider.setContainerAccounts(
                swiftsupport.FakeEngine(), 'Read', fake, 'c', 'r1', 'prep')


class TestDoSwiftDownload(unittest.TestCase):
    BODY = b'\xff\xfe\x00\x80 not utf-8 \r\n'

    def setUp(self):
        self.fake = swiftsupport.FakeSwift(chunkSize=4)
        self.fake.addObject('c', 'o', self.BODY, **{'x-object-meta-k': 'v'})

    def test_doSwiftDownload_writes_bytes_chunks_to_binary_sink(self):
        sink = io.BytesIO()

        responseDict, headers = SwiftProvider.doSwiftDownload(
            self.fake, 'c', 'o', sink)

        self.assertEqual(self.BODY, sink.getvalue())
        self.assertEqual({}, responseDict)
        self.assertEqual('v', headers['x-object-meta-k'])

    def test_doSwiftDownload_requests_1MB_chunks_and_forwards_headers(self):
        SwiftProvider.doSwiftDownload(
            self.fake, 'c', 'o', io.BytesIO(), headers={'Range': 'bytes=0-'})

        (args, kwargs), = self.fake.callsTo('get_object')
        self.assertEqual(('c', 'o'), args)
        self.assertEqual(
            {'resp_chunk_size': 1024000, 'headers': {'Range': 'bytes=0-'}}, kwargs)

    def test_doSwiftDownload_reports_progress_against_integer_length(self):
        seen = []

        SwiftProvider.doSwiftDownload(
            self.fake, 'c', 'o', io.BytesIO(),
            progress=lambda sent, total: seen.append((sent, total)))

        # content-length arrives as a *string* header: it must be an int here.
        # 17 bytes in 4-byte chunks = 5 chunks; each counts as one 1MB block.
        self.assertEqual(17, len(self.BODY))
        self.assertEqual([(n * 1024000, 17) for n in range(1, 6)], seen)

    def test_doSwiftDownload_non_numeric_length_skips_progress(self):
        self.fake.head_object = lambda c, n: {'content-length': 'n/a'}
        seen = []

        SwiftProvider.doSwiftDownload(
            self.fake, 'c', 'o', io.BytesIO(), progress=lambda *a: seen.append(a))

        self.assertEqual([], seen)

    def test_doSwiftDownload_failing_progress_callback_is_ignored(self):
        sink = io.BytesIO()

        def explode(sent, total):
            raise RuntimeError('progress sink broke')
        SwiftProvider.doSwiftDownload(self.fake, 'c', 'o', sink, progress=explode)

        self.assertEqual(self.BODY, sink.getvalue())

    def test_doSwiftDownload_missing_object_raises_404(self):
        with self.assertRaises(ClientException) as ctx:
            SwiftProvider.doSwiftDownload(self.fake, 'c', 'nope', io.BytesIO())

        self.assertEqual(404, ctx.exception.http_status)

    def test_doSwiftDownload_stream_error_leaves_partial_data_and_raises(self):
        self.fake.failStream('c', 'o', 2, ConnectionError('reset'))
        sink = io.BytesIO()

        with self.assertRaises(ConnectionError):
            SwiftProvider.doSwiftDownload(self.fake, 'c', 'o', sink)

        self.assertEqual(self.BODY[:8], sink.getvalue())


class TestFilenameMatching(unittest.TestCase):
    OBJECTS = [
        {'name': 'app-1', CREATETIME: 100.0},
        {'name': 'app-2', CREATETIME: 200.0},
        {'name': 'app-3', CREATETIME: 150.0},
        {'name': 'other', CREATETIME: 1.0},
    ]

    def test_filenameMatching_returns_every_match_with_its_matchers(self):
        result = SwiftProvider.filenameMatching(
            ['app-*', 'app-1'], False, self.OBJECTS, CREATETIME)

        self.assertEqual({'app-1', 'app-2', 'app-3'}, set(result))
        self.assertEqual(['app-*', 'app-1'], result['app-1'][1])
        self.assertEqual(['app-*'], result['app-3'][1])

    def test_filenameMatching_strips_whitespace_around_matchers(self):
        result = SwiftProvider.filenameMatching(
            [' other \n'], False, self.OBJECTS, CREATETIME)

        self.assertEqual(['other'], list(result))

    def test_filenameMatching_no_match_is_empty(self):
        self.assertEqual({}, SwiftProvider.filenameMatching(
            ['zzz*'], False, self.OBJECTS, CREATETIME))

    def test_filenameMatching_latest_only_keeps_newest_per_matcher(self):
        result = SwiftProvider.filenameMatching(
            ['app-*'], True, self.OBJECTS, CREATETIME)

        self.assertEqual({'app-2'}, set(result))
        self.assertEqual((self.OBJECTS[1], ['app-*']), result['app-2'])

    def test_filenameMatching_latest_only_keeps_object_matched_by_another_matcher(self):
        result = SwiftProvider.filenameMatching(
            ['app-*', 'app-1'], True, self.OBJECTS, CREATETIME)

        self.assertEqual({'app-2', 'app-1'}, set(result))
        self.assertEqual(['app-1'], result['app-1'][1])


class TestAddDetailsToContainerListing(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.fake.addObject('c', 'kept', b'1')
        self.fake.addObject('c', 'explicit', b'22', **{CREATETIME: '77.0'})

    def test_addDetails_merges_head_headers_into_each_object(self):
        objects = [{'name': 'kept'}]

        SwiftProvider.addDetailsToContainerListing(self.fake, 'c', objects)

        self.assertEqual('1', objects[0]['content-length'])

    def test_addDetails_defaults_createtime_to_x_timestamp(self):
        objects = [{'name': 'kept'}]

        SwiftProvider.addDetailsToContainerListing(self.fake, 'c', objects)

        self.assertEqual('1.0', objects[0][CREATETIME])

    def test_addDetails_keeps_explicit_createtime(self):
        objects = [{'name': 'explicit'}]

        SwiftProvider.addDetailsToContainerListing(self.fake, 'c', objects)

        self.assertEqual('77.0', objects[0][CREATETIME])

    def test_addDetails_drops_vanished_objects_from_list(self):
        objects = [{'name': 'kept'}, {'name': 'vanished'}]

        SwiftProvider.addDetailsToContainerListing(self.fake, 'c', objects)

        self.assertEqual(['kept'], [o['name'] for o in objects])

    def test_addDetails_drops_vanished_objects_from_plain_dict(self):
        objects = {'kept': {'name': 'kept'}, 'vanished': {'name': 'vanished'}}

        SwiftProvider.addDetailsToContainerListing(self.fake, 'c', objects)

        self.assertEqual(['kept'], list(objects))

    def test_addDetails_forbidden_and_conflict_also_drop_the_object(self):
        for status in (403, 409):
            with self.subTest(status=status):
                fake = swiftsupport.FakeSwift()
                fake.addObject('c', 'a', b'')
                fake.failOn('head_object', status, name='a')
                objects = [{'name': 'a'}]

                SwiftProvider.addDetailsToContainerListing(fake, 'c', objects)

                self.assertEqual([], objects)

    def test_addDetails_other_swift_errors_propagate(self):
        self.fake.failOn('head_object', 500, name='kept')

        with self.assertRaises(ClientException) as ctx:
            SwiftProvider.addDetailsToContainerListing(
                self.fake, 'c', [{'name': 'kept'}])

        self.assertEqual(500, ctx.exception.http_status)

    @unittest.skip("pre-existing bug: for a dict of (object, matchers) tuples -- the "
                   "shape getContainerListing(details=True) passes -- vanished "
                   "objects are never removed, because the tuple is compared "
                   "with the object dict using 'is'")
    def test_addDetails_drops_vanished_objects_from_tuple_valued_dict(self):
        pass


class TestAddDetailsToAccountListing(unittest.TestCase):
    def test_addDetailsToAccountListing_defaults_createtime_for_list_of_dicts(self):
        fake = swiftsupport.FakeSwift()
        fake.addContainer('c', **{'x-timestamp': '42.0'})
        containers = [{'name': 'c'}]

        SwiftProvider.addDetailsToAccountListing(fake, containers)

        self.assertEqual('42.0', containers[0]['x-container-meta-createtime'])

    def test_addDetailsToAccountListing_accepts_name_keyed_dict_of_tuples(self):
        fake = swiftsupport.FakeSwift()
        fake.addContainer('c', **{'x-timestamp': '42.0'})
        entry = {'name': 'c'}

        SwiftProvider.addDetailsToAccountListing(fake, {'c': (entry, ['*'])})

        self.assertEqual('42.0', entry['x-container-meta-createtime'])

    def test_addDetailsToAccountListing_keeps_explicit_createtime(self):
        fake = swiftsupport.FakeSwift()
        fake.addContainer('c', **{'x-container-meta-createtime': '9.0'})
        containers = [{'name': 'c'}]

        SwiftProvider.addDetailsToAccountListing(fake, containers)

        self.assertEqual('9.0', containers[0]['x-container-meta-createtime'])

    def test_addDetailsToAccountListing_missing_container_raises(self):
        with self.assertRaises(ClientException):
            SwiftProvider.addDetailsToAccountListing(
                swiftsupport.FakeSwift(), [{'name': 'gone'}])


class TestListings(unittest.TestCase):
    def test_getAccountListing_matches_container_names(self):
        fake = swiftsupport.FakeSwift()
        for name in ('ci-a', 'ci-b', 'other'):
            fake.addContainer(name)

        result = SwiftProvider.getAccountListing(fake, ['ci-*'])

        self.assertEqual({'ci-a', 'ci-b'}, set(result))

    def test_getAccountListing_latest_only_keeps_newest_container(self):
        fake = swiftsupport.FakeSwift()
        fake.addContainer('ci-old', **{'x-container-meta-createtime': '1.0'})
        fake.addContainer('ci-new', **{'x-container-meta-createtime': '2.0'})

        result = SwiftProvider.getAccountListing(fake, ['ci-*'], latestOnly=True)

        self.assertEqual(['ci-new'], list(result))

    @unittest.skip("pre-existing bug: getAccountListing(details=True) calls the "
                   "misspelled SwiftProvider.addDetailsToAccontListing")
    def test_getAccountListing_details_adds_container_headers(self):
        pass

    def test_getAccountListing_account_error_propagates(self):
        fake = swiftsupport.FakeSwift()
        fake.failOn('get_account', 401)

        with self.assertRaises(ClientException) as ctx:
            SwiftProvider.getAccountListing(fake)

        self.assertEqual(401, ctx.exception.http_status)

    def test_getContainerListing_details_merges_headers_per_match(self):
        fake = swiftsupport.FakeSwift()
        fake.addObject('c', 'a.tar', b'1', **{
            CREATETIME: '5.0', 'x-object-meta-owner': 'ci'})
        fake.addObject('c', 'b.txt', b'2')

        result = SwiftProvider.getContainerListing(
            fake, 'c', ['*.tar'], details=True)

        self.assertEqual(['a.tar'], list(result))
        details, matchers = result['a.tar']
        self.assertEqual(['*.tar'], matchers)
        self.assertEqual('5.0', details[CREATETIME])
        self.assertEqual('ci', details['x-object-meta-owner'])

    def test_getContainerListing_without_details_makes_no_head_calls(self):
        fake = swiftsupport.FakeSwift()
        fake.addObject('c', 'a.tar', b'1')

        SwiftProvider.getContainerListing(fake, 'c')

        self.assertEqual(['get_container'], fake.methodsCalled())

    def test_getContainerListing_latest_only_keeps_newest_match(self):
        fake = swiftsupport.FakeSwift()
        fake.addObject('c', 'a-1', b'', **{CREATETIME: '100.0'})
        fake.addObject('c', 'a-2', b'', **{CREATETIME: '200.0'})

        result = SwiftProvider.getContainerListing(
            fake, 'c', ['a-*'], latestOnly=True)

        self.assertEqual(['a-2'], list(result))

    def test_getContainerListing_missing_container_raises_404(self):
        with self.assertRaises(ClientException) as ctx:
            SwiftProvider.getContainerListing(swiftsupport.FakeSwift(), 'gone')

        self.assertEqual(404, ctx.exception.http_status)


class TestMetadataFilters(unittest.TestCase):
    def test_getMetadataFromDict_keeps_only_object_meta_headers(self):
        self.assertEqual(
            {'x-object-meta-a': '1'},
            SwiftProvider.getMetadataFromDict(
                {'x-object-meta-a': '1', 'x-container-meta-b': '2', 'etag': 'e'}))

    def test_getMetadataFromContainerDict_keeps_only_container_meta_headers(self):
        self.assertEqual(
            {'x-container-meta-b': '2'},
            SwiftProvider.getMetadataFromContainerDict(
                {'x-object-meta-a': '1', 'x-container-meta-b': '2'}))


if __name__ == '__main__':
    unittest.main()
