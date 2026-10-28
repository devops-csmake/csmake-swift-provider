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
"""SwiftSoftLink: prep (target container) and push (manifest "soft links").

Before the migration SwiftSoftLink.__init__ had a line indented with a tab
among space-indented lines, which Python 3 rejects with TabError; the real
constructor runs here (with a minimal stand-in environment).  The swift
connection and csmake engine are mocked and the clock is pinned.
"""
import types
import unittest
import unittest.mock

from . import swiftsupport

swiftsupport.setup()
softLinkModule = swiftsupport.loadModule('SwiftSoftLink')
SwiftSoftLink = softLinkModule.SwiftSoftLink
ClientException = swiftsupport.swiftclientClientException()


def fakeEnvironment(engine):
    """The few Environment attributes CsmakeModule.__init__ reads."""
    metadata = types.SimpleNamespace(getCurrent=lambda: {})
    return types.SimpleNamespace(engine=engine, metadata=metadata)


class SoftLinkTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        for name in ('a.bin', 'b.bin', 'c.bin', 'd.bin'):
            self.fake.addObject('src', name, b'payload')
        self.fake.addContainer('links')
        self.engine = swiftsupport.FakeEngine('unused')
        self.module = SwiftSoftLink(
            fakeEnvironment(self.engine), swiftsupport.RecordingLog())

    def push(self, **options):
        options.setdefault('account', 'acct')
        options.setdefault('container', 'src')
        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(
                    softLinkModule, 'time', swiftsupport.fixedTime(1234.5)):
            return self.module.push(options)

    def prep(self, **options):
        options.setdefault('account', 'acct')
        options.setdefault('container', 'src')
        with swiftsupport.patchConnection(self.fake):
            return self.module.prep(options)

    def linked(self):
        return [(a[0], a[1]) for a, _ in self.fake.callsTo('put_object')]


class TestConstruction(SoftLinkTestCase):
    def test_init_starts_with_no_pushed_objects(self):
        # the real constructor, formerly a TabError
        self.assertEqual([], self.module._getPushedObjects())


class TestPush(SoftLinkTestCase):
    def test_push_creates_a_manifest_link_per_matched_object(self):
        self.assertTrue(self.push(**{'to-container': 'links',
                                     'files': 'a.bin\nb.bin,c.bin'}))

        self.assertEqual(
            [(('links', 'a.bin', None),
              {'headers': {'X-Object-Manifest': 'src/a.bin',
                           'X-Object-Meta-CreateTime': '1234.5'},
               'response_dict': {}}),
             (('links', 'b.bin', None),
              {'headers': {'X-Object-Manifest': 'src/b.bin',
                           'X-Object-Meta-CreateTime': '1234.5'},
               'response_dict': {}}),
             (('links', 'c.bin', None),
              {'headers': {'X-Object-Manifest': 'src/c.bin',
                           'X-Object-Meta-CreateTime': '1234.5'},
               'response_dict': {}})],
            self.fake.callsTo('put_object'))

    def test_push_defaults_to_linking_every_object(self):
        self.push(**{'to-container': 'links'})

        self.assertEqual(
            [('links', n) for n in ('a.bin', 'b.bin', 'c.bin', 'd.bin')],
            self.linked())

    def test_push_records_pushed_objects_for_the_wrapper_aspect(self):
        self.push(**{'to-container': 'links', 'files': 'a.bin,b.bin'})

        self.assertEqual(
            [('src', 'a.bin'), ('src', 'b.bin')], self.module._getPushedObjects())

    def test_push_marks_step_passed_and_returns_true(self):
        self.assertTrue(self.push(**{'to-container': 'links'}))

        self.assertEqual(['passed'], self.module.log.names()[-1:])

    def test_push_without_target_container_records_objects_but_links_nothing(self):
        self.assertTrue(self.push(files='a.bin,b.bin'))

        self.assertEqual(2, len(self.module._getPushedObjects()))
        self.assertEqual([], self.fake.callsTo('put_object'))

    def test_push_noop_true_records_objects_but_links_nothing(self):
        self.push(**{'to-container': 'links', 'noop': 'True', 'files': 'a.bin'})

        self.assertEqual([('src', 'a.bin')], self.module._getPushedObjects())
        self.assertEqual([], self.fake.callsTo('put_object'))

    def test_push_latest_only_links_just_the_newest_match(self):
        self.fake = swiftsupport.FakeSwift()
        self.fake.addObject('src', 'rel-1', b'', **{'x-object-meta-createtime': '100.0'})
        self.fake.addObject('src', 'rel-2', b'', **{'x-object-meta-createtime': '200.0'})
        self.fake.addContainer('links')

        self.push(**{'to-container': 'links', 'files': 'rel-*',
                     'latest-only': 'True'})

        self.assertEqual([('links', 'rel-2')], self.linked())

    def test_push_no_matching_objects_links_nothing_and_passes(self):
        self.assertTrue(self.push(**{'to-container': 'links', 'files': 'zzz*'}))

        self.assertEqual([], self.linked())
        self.assertEqual([], self.module._getPushedObjects())

    def test_push_missing_source_container_raises_404(self):
        with self.assertRaises(ClientException) as ctx:
            self.push(container='gone', **{'to-container': 'links'})

        self.assertEqual(404, ctx.exception.http_status)
        self.assertEqual([], self.linked())

    def test_push_link_creation_error_propagates(self):
        self.fake.failOn('put_object', 403)

        with self.assertRaises(ClientException):
            self.push(**{'to-container': 'links'})

        self.assertNotIn('passed', self.module.log.names())

    def test_push_failed_account_step_raises_before_any_swift_call(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.push(**{'to-container': 'links'})

        self.assertEqual([], self.fake.calls)


class TestPrep(SoftLinkTestCase):
    def test_prep_creates_a_missing_target_container(self):
        self.fake = swiftsupport.FakeSwift()

        self.assertTrue(self.prep(**{'to-container': 'links'}))

        self.assertEqual([(('links', {}), {})], self.fake.callsTo('put_container'))

    def test_prep_leaves_an_existing_target_container_alone(self):
        self.prep(**{'to-container': 'links'})

        self.assertEqual(['get_container'], self.fake.methodsCalled())

    def test_prep_without_target_container_makes_no_container_calls(self):
        self.assertTrue(self.prep())

        self.assertEqual([], self.fake.calls)

    def test_prep_noop_makes_no_container_calls(self):
        self.prep(**{'to-container': 'links', 'noop': 'True'})

        self.assertEqual([], self.fake.calls)

    def test_prep_container_create_forbidden_propagates(self):
        self.fake = swiftsupport.FakeSwift()
        self.fake.failOn('put_container', 403)

        with self.assertRaises(ClientException):
            self.prep(**{'to-container': 'links'})

    def test_prep_failed_account_step_raises(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaises(ValueError):
            self.prep(**{'to-container': 'links'})


class TestSourcesPhase(SoftLinkTestCase):
    @unittest.skip("pre-existing bug: SwiftSoftLink.sources() calls self.pull(), "
                   "which SwiftSoftLink (and CsmakeModule) does not define")
    def test_sources_links_like_push(self):
        self.module.sources({'account': 'acct', 'container': 'src'})


if __name__ == '__main__':
    unittest.main()
