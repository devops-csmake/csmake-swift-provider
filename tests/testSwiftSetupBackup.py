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
"""SwiftSetupBackup: the backup container name goes into the
x-versions-location header via urllib.parse.quote (Python 2's urllib.quote
no longer exists)."""
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftSetupBackup = swiftsupport.loadModule('SwiftSetupBackup').SwiftSetupBackup


# space, '/', and two non-ASCII letters (u-umlaut, i-umlaut)
NAME = 'my backup/v1 \N{LATIN SMALL LETTER U WITH DIAERESIS}n\N{LATIN SMALL LETTER I WITH DIAERESIS}'


class TestSwiftSetupBackup(unittest.TestCase):
    def prep(self, backupName):
        fake = swiftsupport.FakeSwift()
        fake.addObject('data', 'existing.txt', b'hi')
        fake.containers['data']['headers']['x-container-meta-owner'] = 'build'
        module = swiftsupport.makeModule(
            SwiftSetupBackup, swiftsupport.FakeEngine())
        options = {'account': 'acct', 'container': 'data',
                   'backup': backupName}
        with swiftsupport.patchConnection(fake):
            self.assertTrue(module.prep(options))
        return fake, module

    def testBackupNameIsUrlQuotedIntoVersionsLocation(self):
        fake, module = self.prep(NAME)

        # spaces and non-ASCII are percent-encoded (UTF-8), '/' is kept
        posts = fake.callsTo('post_container')
        self.assertEqual(1, len(posts))
        (container, headers), _ = posts[0]
        self.assertEqual('data', container)
        self.assertEqual(
            'my%20backup/v1%20%C3%BCn%C3%AF', headers['x-versions-location'])
        # existing container metadata is carried through the POST
        self.assertEqual('build', headers['x-container-meta-owner'])
        # the backup container was created
        self.assertIn(NAME, fake.containers)
        self.assertEqual(['passed'], module.log.names()[-1:])


if __name__ == '__main__':
    unittest.main()
