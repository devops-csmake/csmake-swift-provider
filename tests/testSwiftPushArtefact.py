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
"""SwiftPushArtefact: prep (containers/ACLs) and push (upload local files).

The swift connection, the csmake engine and the file mapping are mocked.
Real temp files are used for push because the open mode is what is under
test: the file must be opened binary ('rb') and handed to swiftclient as a
bytes stream, whatever its contents.
"""
import datetime
import os
import shutil
import tempfile
import threading
import time as realtime
import types
import unittest
import unittest.mock

from . import swiftsupport

swiftsupport.setup()
pushModule = swiftsupport.loadModule('SwiftPushArtefact')
SwiftPushArtefact = pushModule.SwiftPushArtefact
ClientException = swiftsupport.swiftclientClientException()

# not valid UTF-8; every byte value; CR/LF and ^Z
BINARY = b'\xff\xfe\x00\x80' + bytes(range(256)) + b'\r\n\x1a\r\n'


class PushTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='swiftpush')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = swiftsupport.FakeSwift()
        self.engine = swiftsupport.FakeEngine()
        self.module = swiftsupport.makeModule(SwiftPushArtefact, self.engine)

    def writeFile(self, relname, data):
        path = os.path.join(self.tmp, *relname.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def mapFiles(self, files, containers):
        """files: [(relLocation, data)], containers: [relLocation, ...]"""
        froms = [{'relLocation': rel,
                  'location': self.writeFile(rel.lstrip('./'), data)}
                 for rel, data in files]
        tos = [{'relLocation': c, 'location': c} for c in containers]
        self.module.mapping = swiftsupport.FakeMapping((froms, tos))

    def push(self, **options):
        options.setdefault('account', 'acct')
        options.setdefault('progress', 'False')
        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(
                    pushModule, 'time', swiftsupport.fixedTime(1234.5)):
            return self.module.push(options)

    def prep(self, **options):
        options.setdefault('account', 'acct')
        with swiftsupport.patchConnection(self.fake):
            return self.module.prep(options)


class TestPush(PushTestCase):
    def test_push_uploads_non_utf8_file_bytes_unchanged(self):
        self.mapFiles([('./dir/blob.bin', BINARY)], ['artefacts'])

        self.assertTrue(self.push())

        self.assertEqual(BINARY, self.fake.uploaded[('artefacts', 'dir/blob.bin')])

    def test_push_opens_the_source_file_in_binary_mode(self):
        self.mapFiles([('blob.bin', BINARY)], ['artefacts'])

        self.push()

        self.assertEqual('rb', self.fake.uploadModes[('artefacts', 'blob.bin')])

    def test_push_passes_length_chunk_size_and_createtime_header(self):
        self.mapFiles([('blob.bin', BINARY)], ['artefacts'])

        self.push()

        (args, kwargs), = self.fake.callsTo('put_object')
        self.assertEqual(('artefacts', 'blob.bin'), args[:2])
        self.assertEqual(len(BINARY), kwargs['content_length'])
        self.assertEqual(10240, kwargs['chunk_size'])
        self.assertEqual({'X-Object-Meta-CreateTime': '1234.5'}, kwargs['headers'])

    def test_push_strips_leading_dot_slash_from_object_name(self):
        self.mapFiles([('./top.bin', b'x')], ['artefacts'])

        self.push()

        self.assertEqual(['top.bin'], [a[1] for a, _ in self.fake.callsTo('put_object')])

    def test_push_container_path_selects_container_and_object_name(self):
        self.mapFiles([('blob.bin', b'x')], ['bucket/renamed/obj.bin'])

        self.push()

        self.assertEqual(
            [('bucket', 'renamed/obj.bin')],
            [a[:2] for a, _ in self.fake.callsTo('put_object')])

    def test_push_records_pushed_objects_for_the_wrapper_aspect(self):
        self.mapFiles([('a.bin', b'1'), ('b.bin', b'2')], ['artefacts'])

        self.push()

        self.assertEqual(
            [('artefacts', 'a.bin'), ('artefacts', 'b.bin')],
            self.module._getPushedObjects())

    def test_push_uploads_to_every_destination_container(self):
        self.mapFiles([('a.bin', b'1')], ['one', 'two/renamed.bin'])

        self.push()

        self.assertEqual(
            [('one', 'a.bin'), ('two', 'renamed.bin')],
            [a[:2] for a, _ in self.fake.callsTo('put_object')])
        self.assertEqual(
            [('one', 'a.bin'), ('two', 'renamed.bin')],
            self.module._getPushedObjects())

    def test_push_empty_file_uploads_zero_bytes(self):
        self.mapFiles([('empty.bin', b'')], ['artefacts'])

        self.push()

        (args, kwargs), = self.fake.callsTo('put_object')
        self.assertEqual(0, kwargs['content_length'])
        self.assertEqual(b'', self.fake.uploaded[('artefacts', 'empty.bin')])

    def test_push_expires_sets_delete_after_in_seconds(self):
        self.mapFiles([('a.bin', b'1')], ['artefacts'])

        self.push(expires='1d 2h')

        (_, kwargs), = self.fake.callsTo('put_object')
        self.assertEqual('93600', kwargs['headers']['X-Delete-After'])

    def test_push_without_expires_sets_no_delete_after(self):
        self.mapFiles([('a.bin', b'1')], ['artefacts'])

        self.push()

        (_, kwargs), = self.fake.callsTo('put_object')
        self.assertNotIn('X-Delete-After', kwargs['headers'])

    def test_push_marks_step_passed_and_returns_true(self):
        self.mapFiles([('a.bin', b'1')], ['artefacts'])

        self.assertTrue(self.push())

        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_push_missing_source_file_raises_before_uploading(self):
        self.mapFiles([('a.bin', b'1')], ['artefacts'])
        os.remove(self.module.mapping.specs[0][0][0]['location'])

        with self.assertRaises(FileNotFoundError):
            self.push()

        self.assertEqual([], self.fake.callsTo('put_object'))
        self.assertEqual([], self.module._getPushedObjects())

    def test_push_upload_error_propagates_and_is_not_recorded(self):
        self.mapFiles([('a.bin', b'1'), ('b.bin', b'2')], ['artefacts'])
        self.fake.failOn('put_object', 500, name='a.bin')

        with self.assertRaises(ClientException) as ctx:
            self.push()

        self.assertEqual(500, ctx.exception.http_status)
        self.assertEqual(1, len(self.fake.callsTo('put_object')))
        self.assertEqual([], self.module._getPushedObjects())
        self.assertNotIn('passed', self.module.log.names())

    def test_push_failed_account_step_raises_before_any_upload(self):
        self.mapFiles([('a.bin', b'1')], ['artefacts'])
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.push()

        self.assertEqual([], self.fake.calls)

    def test_push_does_not_validate_mapped_files(self):
        self.mapFiles([('a.bin', b'1')], ['artefacts'])

        self.push()

        self.assertFalse(self.module.validateFiles)


class TestPushProgress(PushTestCase):
    def test_push_progress_reports_transfer_percentage_and_stops_reporter(self):
        self.mapFiles([('blob.bin', BINARY)], ['artefacts'])
        log = self.module.log

        class WaitsForReport(swiftsupport.FakeSwift):
            """put_object() returns only once the reporter has logged."""
            def put_object(innerself, *args, **kwargs):
                swiftsupport.FakeSwift.put_object(innerself, *args, **kwargs)
                deadline = realtime.monotonic() + 5
                while 'info' not in log.names() and realtime.monotonic() < deadline:
                    realtime.sleep(0.001)
        self.fake = WaitsForReport()
        # sleep() is near-instant so the reporter's 20 ticks pass quickly, and
        # the clock advances 1s per reading so the transfer rate is computable
        ticks = iter(range(1, 10000))
        fastTime = swiftsupport.fixedTime(1234.5)
        fastTime.sleep = lambda seconds: realtime.sleep(0.0005)
        fastDatetime = types.SimpleNamespace(datetime=types.SimpleNamespace(
            utcnow=lambda: datetime.datetime(2020, 1, 1) + datetime.timedelta(
                seconds=next(ticks))))
        threadsBefore = threading.active_count()

        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(pushModule, 'time', fastTime), \
                unittest.mock.patch.object(pushModule, 'datetime', fastDatetime):
            self.assertTrue(self.module.push({'account': 'acct'}))

        message = log.messages('info')[0]
        self.assertRegex(
            message,
            r'^\[artefacts:blob\.bin\] Transferred \d+% \(\d+ out of '
            + str(len(BINARY)) + r'  - \d+\.\d\d(KB|MB|GB)/s\)$')
        self.assertEqual(threadsBefore, threading.active_count())


class TestPrep(PushTestCase):
    def mapContainers(self, *relLocations):
        self.module.mapping = swiftsupport.FakeMapping(
            ([], [{'relLocation': c, 'location': c} for c in relLocations]))

    def test_prep_creates_every_missing_destination_container(self):
        self.mapContainers('one/obj', 'two')

        self.assertTrue(self.prep())

        self.assertEqual(
            ['get_container', 'put_container', 'get_container', 'put_container'],
            self.fake.methodsCalled())
        self.assertEqual(
            [(('one', {}), {}), (('two', {}), {})],
            self.fake.callsTo('put_container'))

    def test_prep_leaves_existing_container_alone(self):
        self.fake.addContainer('one')
        self.mapContainers('one')

        self.prep()

        self.assertEqual([], self.fake.callsTo('put_container'))

    def test_prep_access_grants_read_on_each_container(self):
        self.engine.accounts['reader'] = ({}, {'account': 'pR', 'user': 'uR'})
        self.mapContainers('one', 'two')

        self.prep(access='reader')

        self.assertEqual(
            [(('one', {'X-Container-Read': 'pR:uR'}), {}),
             (('two', {'X-Container-Read': 'pR:uR'}), {})],
            self.fake.callsTo('post_container'))

    def test_prep_without_access_posts_no_acl(self):
        self.mapContainers('one')

        self.prep()

        self.assertEqual([], self.fake.callsTo('post_container'))

    def test_prep_does_not_validate_mapped_files(self):
        self.mapContainers('one')

        self.prep()

        self.assertFalse(self.module.validateFiles)

    def test_prep_failed_account_step_raises_and_touches_nothing(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)
        self.mapContainers('one')

        with self.assertRaises(ValueError):
            self.prep()

        self.assertEqual([], self.fake.calls)

    def test_prep_container_create_forbidden_propagates(self):
        self.fake.failOn('put_container', 403)
        self.mapContainers('one')

        with self.assertRaises(ClientException):
            self.prep()

        self.assertNotIn('passed', self.module.log.names())


if __name__ == '__main__':
    unittest.main()
