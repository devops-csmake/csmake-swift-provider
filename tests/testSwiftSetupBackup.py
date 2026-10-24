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
"""SwiftSetupBackup: create the backup container and point the source
container's x-versions-location at it (the name goes through
urllib.parse.quote; Python 2's urllib.quote no longer exists).

The swift connection and csmake engine are mocked; call order on the fake
connection is asserted because the backup container must exist before the
source container is pointed at it.
"""
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftSetupBackup = swiftsupport.loadModule('SwiftSetupBackup').SwiftSetupBackup
ClientException = swiftsupport.swiftclientClientException()

# space, '/', and two non-ASCII letters (u-umlaut, i-umlaut)
NAME = 'my backup/v1 \N{LATIN SMALL LETTER U WITH DIAERESIS}n\N{LATIN SMALL LETTER I WITH DIAERESIS}'
QUOTED = 'my%20backup/v1%20%C3%BCn%C3%AF'


class BackupTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.fake.addObject('data', 'existing.txt', b'hi',)
        self.fake.addContainer('data', **{'x-container-meta-owner': 'build'})
        self.engine = swiftsupport.FakeEngine(phase='prep')
        self.module = swiftsupport.makeModule(SwiftSetupBackup, self.engine)

    def prep(self, backup='data-backup', **options):
        options.update({'account': 'acct', 'container': 'data', 'backup': backup})
        with swiftsupport.patchConnection(self.fake):
            return self.module.prep(options)

    def versionsPost(self):
        posts = [a for a, _ in self.fake.callsTo('post_container') if a[0] == 'data']
        self.assertEqual(1, len(posts))
        return posts[0][1]


class TestPrep(BackupTestCase):
    def test_prep_quotes_backup_name_into_versions_location(self):
        self.prep(NAME)

        # spaces and non-ASCII are percent-encoded (UTF-8), '/' is kept
        self.assertEqual(QUOTED, self.versionsPost()['x-versions-location'])

    def test_prep_plain_backup_name_is_used_as_is(self):
        self.prep('data-backup')

        self.assertEqual('data-backup', self.versionsPost()['x-versions-location'])

    def test_prep_carries_existing_container_metadata_into_the_post(self):
        self.prep()

        self.assertEqual('build', self.versionsPost()['x-container-meta-owner'])

    def test_prep_creates_the_backup_container_before_versioning_the_source(self):
        self.prep(NAME)

        self.assertEqual(
            [('get_container', (NAME,)), ('put_container', (NAME, {})),
             ('get_container', ('data',)), ('head_container', ('data',)),
             ('post_container', ('data', self.versionsPost()))],
            [(m, a) for m, a, _ in self.fake.calls])

    def test_prep_existing_backup_container_is_not_recreated(self):
        self.fake.addContainer('data-backup')

        self.prep()

        self.assertEqual([], self.fake.callsTo('put_container'))

    def test_prep_access_grants_read_on_backup_container_before_versioning(self):
        self.engine.accounts['reader'] = ({}, {'account': 'pR', 'user': 'uR'})

        self.prep(access='reader')

        posts = [a for a, _ in self.fake.callsTo('post_container')]
        self.assertEqual(
            [('data-backup', {'X-Container-Read': 'pR:uR'}), 'data'],
            [posts[0], posts[1][0]])

    def test_prep_without_access_sets_no_acl(self):
        self.prep()

        self.assertEqual(['data'], [a[0] for a, _ in self.fake.callsTo('post_container')])

    def test_prep_returns_true_and_marks_passed(self):
        self.assertTrue(self.prep())

        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_prep_does_not_validate_mapped_files(self):
        self.prep()

        self.assertFalse(self.module.validateFiles)


class TestPrepFailures(BackupTestCase):
    def test_prep_failed_account_step_raises_and_touches_nothing(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.prep()

        self.assertEqual([], self.fake.calls)

    def test_prep_missing_source_container_raises_without_versioning(self):
        del self.fake.containers['data']

        with self.assertRaises(ClientException) as ctx:
            self.prep()

        self.assertEqual(404, ctx.exception.http_status)
        self.assertEqual([], self.fake.callsTo('post_container'))
        self.assertNotIn('passed', self.module.log.names())

    def test_prep_backup_container_create_forbidden_propagates(self):
        self.fake.failOn('put_container', 403)

        with self.assertRaises(ClientException):
            self.prep()

        self.assertEqual([], self.fake.callsTo('post_container'))

    def test_prep_versioning_post_forbidden_propagates(self):
        self.fake.failOn('post_container', 403, container='data')

        with self.assertRaises(ClientException):
            self.prep()

        self.assertNotIn('passed', self.module.log.names())

    def test_prep_failed_reader_step_raises_before_versioning(self):
        self.engine.results['reader'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'reader step failed'):
            self.prep(access='reader')

        self.assertEqual([], self.fake.callsTo('post_container'))


if __name__ == '__main__':
    unittest.main()
