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
"""SwiftPullArtefact: download objects from a container to local files.

swiftclient streams object bodies as *bytes*.  The pull step therefore has
to open the download target 'wb', and open an existing local file 'rb' to
compute its md5 for the "already up to date" check.  Text mode (the Python 2
spelling) either raises TypeError on write or UnicodeDecodeError on read, or
silently corrupts the data.  The bodies here are deliberately not valid
UTF-8, and real temp files are used because open mode is what is under test.
The swift connection and csmake engine are mocked; swift failures (404, 5xx,
a stream cut mid-transfer) are scripted on the fake connection.
"""
import datetime
import hashlib
import os
import shutil
import tempfile
import types
import unittest
import unittest.mock
import warnings

from . import swiftsupport

swiftsupport.setup()
pullModule = swiftsupport.loadModule('SwiftPullArtefact')
SwiftPullArtefact = pullModule.SwiftPullArtefact
ClientException = swiftsupport.swiftclientClientException()

# Not valid UTF-8 (0xff 0xfe 0x00 0x80), every byte value, CR/LF and ^Z.
BINARY = b'\xff\xfe\x00\x80' + bytes(range(256)) + b'\r\n\x1a\r\n'
NON_ASCII = 'r\N{LATIN SMALL LETTER E WITH ACUTE}sum\N{LATIN SMALL LETTER E WITH ACUTE}.bin'


class PullTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='swiftpull')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = swiftsupport.FakeSwift(chunkSize=7)
        self.engine = swiftsupport.FakeEngine(self.tmp)
        self.module = swiftsupport.makeModule(SwiftPullArtefact, self.engine)
        self.options = {
            'account': 'acct', 'container': 'artefacts',
            'result-dir': self.tmp, 'progress': 'False'}

    def pull(self):
        with swiftsupport.patchConnection(self.fake), \
                warnings.catch_warnings():
            # the module uses datetime.utcnow(), deprecated since 3.12
            warnings.filterwarnings(
                'ignore', message='datetime.datetime.utc',
                category=DeprecationWarning)
            return self.module.pull(self.options)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def read(self, *parts):
        with open(self.path(*parts), 'rb') as f:
            return f.read()

    def writeLocal(self, name, data):
        with open(self.path(name), 'wb') as f:
            f.write(data)


class TestDownload(PullTestCase):
    def test_pull_writes_non_utf8_body_byte_identical(self):
        self.fake.addObject('artefacts', 'top.bin', BINARY)

        self.assertTrue(self.pull())

        self.assertEqual(BINARY, self.read('top.bin'))

    def test_pull_nested_object_name_creates_directories(self):
        self.fake.addObject('artefacts', 'sub/dir/nested.bin', BINARY[::-1])

        self.assertTrue(self.pull())

        self.assertEqual(BINARY[::-1], self.read('sub', 'dir', 'nested.bin'))

    def test_pull_non_ascii_object_name_is_written_under_that_name(self):
        self.fake.addObject('artefacts', NON_ASCII, b'\x80body')

        self.assertTrue(self.pull())

        self.assertEqual(b'\x80body', self.read(NON_ASCII))

    def test_pull_zero_byte_object_creates_empty_file(self):
        self.fake.addObject('artefacts', 'empty.bin', b'')

        self.assertTrue(self.pull())

        self.assertEqual(b'', self.read('empty.bin'))

    def test_pull_marks_step_passed(self):
        self.fake.addObject('artefacts', 'a.bin', b'1')

        self.pull()

        self.assertEqual(['passed'], self.module.log.names()[-1:])
        self.assertNotIn('failed', self.module.log.names())

    def test_pull_requests_each_object_once_with_1MB_chunks(self):
        self.fake.addObject('artefacts', 'a.bin', b'1')

        self.pull()

        self.assertEqual(
            [(('artefacts', 'a.bin'), {'resp_chunk_size': 1024000, 'headers': None})],
            self.fake.callsTo('get_object'))

    def test_pull_files_option_downloads_only_matching_objects(self):
        for name in ('a.bin', 'b.bin', 'c1', 'c2', 'd.txt'):
            self.fake.addObject('artefacts', name, b'x')
        self.options['files'] = 'a*\nb.bin,c?'

        self.pull()

        self.assertEqual(
            ['a.bin', 'b.bin', 'c1', 'c2'],
            sorted(a[1] for a, _ in self.fake.callsTo('get_object')))

    def test_pull_empty_container_downloads_nothing_and_passes(self):
        self.fake.addContainer('artefacts')

        self.assertTrue(self.pull())

        self.assertEqual([], self.fake.callsTo('get_object'))
        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_pull_defaults_target_directory_to_engine_results_dir(self):
        del self.options['result-dir']
        self.fake.addObject('artefacts', 'a.bin', b'1')

        self.pull()

        self.assertEqual(b'1', self.read('a.bin'))


class TestUpToDateCheck(PullTestCase):
    def test_pull_skips_download_when_local_md5_matches_etag(self):
        # the md5 of the local file (read 'rb') must equal the object's hash
        self.fake.addObject('artefacts', 'same.bin', BINARY)
        self.writeLocal('same.bin', BINARY)

        self.assertTrue(self.pull())

        self.assertEqual([], self.fake.callsTo('get_object'))
        self.assertEqual(BINARY, self.read('same.bin'))

    def test_pull_logs_that_an_up_to_date_file_was_skipped(self):
        self.fake.addObject('artefacts', 'same.bin', BINARY)
        self.writeLocal('same.bin', BINARY)

        self.pull()

        self.assertEqual(
            ["'%s' is already up-to-date, not redownloading" % self.path('same.bin')],
            self.module.log.messages('info'))

    def test_pull_replaces_local_file_when_md5_differs(self):
        newBody = b'\x80\x81\xfe\xffnew contents\x00'
        self.assertNotEqual(
            hashlib.md5(newBody).hexdigest(), hashlib.md5(BINARY).hexdigest())
        self.fake.addObject('artefacts', 'stale.bin', newBody)
        self.writeLocal('stale.bin', BINARY)

        self.assertTrue(self.pull())

        self.assertEqual(1, len(self.fake.callsTo('get_object')))
        self.assertEqual(newBody, self.read('stale.bin'))

    def test_pull_replaces_empty_local_file_for_non_empty_object(self):
        self.fake.addObject('artefacts', 'was-empty.bin', BINARY)
        self.writeLocal('was-empty.bin', b'')

        self.pull()

        self.assertEqual(BINARY, self.read('was-empty.bin'))

    def test_pull_up_to_date_and_stale_files_are_handled_independently(self):
        self.fake.addObject('artefacts', 'same.bin', BINARY)
        self.fake.addObject('artefacts', 'stale.bin', b'fresh')
        self.writeLocal('same.bin', BINARY)
        self.writeLocal('stale.bin', b'\xff old')

        self.pull()

        self.assertEqual(
            [(('artefacts', 'stale.bin'),
              {'resp_chunk_size': 1024000, 'headers': None})],
            self.fake.callsTo('get_object'))


class TestDownloadFailures(PullTestCase):
    def test_pull_object_gone_404_is_tolerated_and_leaves_no_file(self):
        self.fake.addObject('artefacts', 'gone.bin', b'x')
        self.fake.failOn('get_object', 404, name='gone.bin')

        self.assertTrue(self.pull())

        self.assertFalse(os.path.exists(self.path('gone.bin')))
        self.assertTrue(any('returned 404' in m
                            for m in self.module.log.messages('exception')))
        self.assertEqual(1, len(self.module.log.messages('warning')))

    def test_pull_object_conflict_409_is_tolerated(self):
        self.fake.addObject('artefacts', 'gone.bin', b'x')
        self.fake.failOn('get_object', 409)

        self.assertTrue(self.pull())

        self.assertFalse(os.path.exists(self.path('gone.bin')))

    def test_pull_server_error_fails_the_step_and_removes_partial_file(self):
        self.fake.addObject('artefacts', 'a.bin', b'x')
        self.fake.failOn('get_object', 500)

        self.assertFalse(self.pull())

        self.assertFalse(os.path.exists(self.path('a.bin')))
        self.assertEqual(['failed'], self.module.log.names()[-1:])
        self.assertNotIn('passed', self.module.log.names())

    def test_pull_stream_cut_mid_transfer_fails_and_removes_partial_file(self):
        self.fake.addObject('artefacts', 'a.bin', BINARY)
        self.fake.failStream('artefacts', 'a.bin', 3, ConnectionResetError('cut'))

        self.assertFalse(self.pull())

        self.assertFalse(os.path.exists(self.path('a.bin')))
        self.assertEqual(['failed'], self.module.log.names()[-1:])

    def test_pull_one_failed_download_does_not_stop_the_others(self):
        self.fake.addObject('artefacts', 'bad.bin', b'x')
        self.fake.addObject('artefacts', 'good.bin', BINARY)
        self.fake.failOn('get_object', 500, name='bad.bin')

        self.assertFalse(self.pull())

        self.assertEqual(BINARY, self.read('good.bin'))

    def test_pull_ignore_fail_passes_despite_a_failed_download(self):
        self.options['ignore-fail'] = 'True'
        self.fake.addObject('artefacts', 'a.bin', b'x')
        self.fake.failOn('get_object', 500)

        self.assertTrue(self.pull())

        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_pull_missing_container_raises_404(self):
        with self.assertRaises(ClientException) as ctx:
            self.pull()

        self.assertEqual(404, ctx.exception.http_status)
        self.assertNotIn('passed', self.module.log.names())

    def test_pull_missing_container_with_ignore_fail_returns_false_but_passes(self):
        self.options['ignore-fail'] = 'True'

        self.assertFalse(self.pull())

        self.assertEqual(['passed'], self.module.log.names()[-1:])
        self.assertEqual([], self.fake.callsTo('get_object'))

    def test_pull_failed_account_step_raises_before_any_swift_call(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.pull()

        self.assertEqual([], self.fake.calls)


class TestProgressReport(PullTestCase):
    """The download thread reports "Transferred n%" at most every 2 seconds."""
    SMALL = b'\xff\xfe\x00\x80ab'     # one fake chunk, 6 bytes

    def pullWithClock(self, *readings):
        times = iter(readings)
        clock = types.SimpleNamespace(datetime=types.SimpleNamespace(
            utcnow=lambda: next(times)))
        self.fake.addObject('artefacts', 'a.bin', self.SMALL)
        with unittest.mock.patch.object(pullModule, 'datetime', clock):
            return self.pull()

    def test_pull_progress_logs_clamped_percentage_and_rate(self):
        self.options['progress'] = 'True'
        start = datetime.datetime(2020, 1, 1)

        self.assertTrue(self.pullWithClock(start, start + datetime.timedelta(seconds=5)))

        # one 1,024,000-byte "block" counted for a 6-byte object: clamped to 100%
        self.assertEqual(
            ['[artefacts:%s] Transferred 100.0%% (1024000 out of 6 - 204.80KB/s)'
             % self.path('a.bin')],
            self.module.log.messages('info'))

    def test_pull_progress_is_throttled_to_two_second_intervals(self):
        self.options['progress'] = 'True'
        start = datetime.datetime(2020, 1, 1)

        self.pullWithClock(start, start + datetime.timedelta(seconds=1))

        self.assertEqual([], self.module.log.messages('info'))

    def test_pull_progress_false_logs_no_transfer_report(self):
        self.options['progress'] = 'False'
        start = datetime.datetime(2020, 1, 1)

        self.pullWithClock(start, start + datetime.timedelta(seconds=5))

        self.assertEqual([], self.module.log.messages('info'))


if __name__ == '__main__':
    unittest.main()
