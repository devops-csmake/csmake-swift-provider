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
"""SwiftPullArtefact: binary-safe downloads and local md5 comparison.

swiftclient streams object bodies as *bytes*.  The pull step therefore has
to open the download target 'wb', and open an existing local file 'rb' to
compute its md5 for the "already up to date" check.  Text mode (the Python 2
spelling) either raises TypeError on write or UnicodeDecodeError on read, or
silently corrupts the data.  The bodies here are deliberately not valid
UTF-8.  SwiftProvider, the real download thread, real files and the real
CsmakeModule._fileMD5 are all exercised; only the swift connection is fake.
"""
import hashlib
import os
import shutil
import tempfile
import unittest
import warnings

from . import swiftsupport

swiftsupport.setup()
SwiftPullArtefact = swiftsupport.loadModule('SwiftPullArtefact').SwiftPullArtefact

# Not valid UTF-8 (0xff 0xfe 0x00 0x80), every byte value, CR/LF and ^Z.
BINARY = b'\xff\xfe\x00\x80' + bytes(range(256)) + b'\r\n\x1a\r\n'


class TestSwiftPullArtefact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='swiftpull')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = swiftsupport.FakeSwift(chunkSize=7)
        self.module = swiftsupport.makeModule(
            SwiftPullArtefact, swiftsupport.FakeEngine(self.tmp))
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

    def read(self, *parts):
        with open(os.path.join(self.tmp, *parts), 'rb') as f:
            return f.read()

    def testDownloadIsByteIdentical(self):
        self.fake.addObject('artefacts', 'top.bin', BINARY)
        self.fake.addObject('artefacts', 'sub/dir/nested.bin', BINARY[::-1])

        self.assertTrue(self.pull())

        self.assertEqual(BINARY, self.read('top.bin'))
        self.assertEqual(BINARY[::-1], self.read('sub', 'dir', 'nested.bin'))
        self.assertEqual(['passed'], self.module.log.names()[-1:])
        self.assertNotIn('failed', self.module.log.names())

    def testUpToDateBinaryFileIsNotRedownloaded(self):
        # The md5 of the local file (read 'rb') must equal the object's hash
        self.fake.addObject('artefacts', 'same.bin', BINARY)
        with open(os.path.join(self.tmp, 'same.bin'), 'wb') as f:
            f.write(BINARY)

        self.assertTrue(self.pull())

        self.assertEqual([], self.fake.callsTo('get_object'))
        self.assertEqual(BINARY, self.read('same.bin'))
        self.assertIn('info', self.module.log.names())

    def testStaleBinaryFileIsReplaced(self):
        newBody = b'\x80\x81\xfe\xffnew contents\x00'
        self.assertNotEqual(
            hashlib.md5(newBody).hexdigest(), hashlib.md5(BINARY).hexdigest())
        self.fake.addObject('artefacts', 'stale.bin', newBody)
        with open(os.path.join(self.tmp, 'stale.bin'), 'wb') as f:
            f.write(BINARY)

        self.assertTrue(self.pull())

        self.assertEqual(1, len(self.fake.callsTo('get_object')))
        self.assertEqual(newBody, self.read('stale.bin'))


if __name__ == '__main__':
    unittest.main()
