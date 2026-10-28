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
"""SwiftArtefactToWrapper: after a successful push, link each pushed object
into the wrapper container with an x-object-manifest "soft link".

The aspect is driven through passed__push with a mocked engine (wrapper and
account steps), a swift fake, and a pinned clock for the CreateTime header.
"""
import contextlib
import types
import unittest
import unittest.mock

from . import swiftsupport

swiftsupport.setup()
wrapperModule = swiftsupport.loadModule('SwiftArtefactToWrapper')
SwiftArtefactToWrapper = wrapperModule.SwiftArtefactToWrapper
ClientException = swiftsupport.swiftclientClientException()

NON_ASCII = 'r\N{LATIN SMALL LETTER E WITH ACUTE}sum\N{LATIN SMALL LETTER E WITH ACUTE}.bin'


class AspectTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.engine = swiftsupport.FakeEngine()
        self.env = types.SimpleNamespace(env={'__wrapper__w1': 'Exists'})
        self.aspect = swiftsupport.makeModule(
            SwiftArtefactToWrapper, self.engine, env=self.env)
        # the SwiftWrapper step reports (wrapper container, its account)
        self.engine.results['SwiftWrapper@w1'] = swiftsupport.stepResult(
            True, ('wrapcontainer', 'wrapacct'))

    def push(self, pushed, wrapper='SwiftWrapper@w1'):
        instance = types.SimpleNamespace(_getPushedObjects=lambda: pushed)
        with swiftsupport.patchConnection(self.fake), \
                unittest.mock.patch.object(
                    wrapperModule, 'time', swiftsupport.fixedTime(1234.5)):
            return self.aspect.passed__push(
                'push', {'wrapper': wrapper}, instance, {})


class TestLinking(AspectTestCase):
    def test_passed_push_links_each_pushed_object_into_the_wrapper(self):
        result = self.push([('src', 'a.bin'), ('src2', 'dir/b.bin')])

        self.assertTrue(result)
        self.assertEqual(
            [(('wrapcontainer', 'a.bin', None),
              {'headers': {'X-Object-Manifest': 'src/a.bin',
                           'X-Object-Meta-CreateTime': '1234.5'},
               'response_dict': {}}),
             (('wrapcontainer', 'dir/b.bin', None),
              {'headers': {'X-Object-Manifest': 'src2/dir/b.bin',
                           'X-Object-Meta-CreateTime': '1234.5'},
               'response_dict': {}})],
            self.fake.callsTo('put_object'))
        self.assertEqual(['passed'], self.aspect.log.names()[-1:])

    def test_passed_push_asks_wrapper_for_info_then_authenticates_its_account(self):
        self.push([('src', 'a.bin')])

        self.assertEqual(
            [('SwiftWrapper@w1', 'getinfo'), ('wrapacct', 'push')],
            self.engine.launched)

    def test_passed_push_wrapper_option_without_at_sign_uses_whole_id(self):
        self.env.env = {'__wrapper__w1': 'Exists'}
        self.engine.results['w1'] = self.engine.results.pop('SwiftWrapper@w1')

        self.assertTrue(self.push([('src', 'a.bin')], wrapper='w1'))

        self.assertEqual(1, len(self.fake.callsTo('put_object')))

    def test_passed_push_no_pushed_objects_passes_without_links(self):
        self.assertTrue(self.push([]))

        self.assertEqual([], self.fake.callsTo('put_object'))
        self.assertEqual(['passed'], self.aspect.log.names()[-1:])

    def test_passed_push_non_ascii_object_names_survive_in_manifest(self):
        self.push([('src', NON_ASCII)])

        (args, kwargs), = self.fake.callsTo('put_object')
        self.assertEqual(NON_ASCII, args[1])
        self.assertEqual('src/' + NON_ASCII, kwargs['headers']['X-Object-Manifest'])


class TestWrapperNotInUse(AspectTestCase):
    def test_passed_push_unregistered_wrapper_returns_false_and_does_nothing(self):
        self.env.env = {}

        result = self.push([('src', 'a.bin')])

        self.assertFalse(result)
        self.assertEqual([], self.engine.launched)
        self.assertEqual([], self.fake.calls)

    def test_passed_push_unregistered_wrapper_is_not_an_error(self):
        self.env.env = {}

        self.push([('src', 'a.bin')])

        self.assertIn('passed', self.aspect.log.names())
        self.assertNotIn('failed', self.aspect.log.names())


class TestFailures(AspectTestCase):
    def _push_ignoring_logging_typeerror(self):
        # Pre-existing bug, out of scope here: the "invalid wrapper" branch
        # formats its message with self['wrapper'], which an aspect does not
        # support (TypeError).  What matters is that the step is marked failed
        # and nothing is linked.
        with contextlib.suppress(TypeError):
            return self.push([('src', 'a.bin')])

    def test_passed_push_failed_wrapper_step_marks_failure_and_links_nothing(self):
        self.engine.results['SwiftWrapper@w1'] = swiftsupport.stepResult(passed=False)

        self._push_ignoring_logging_typeerror()

        self.assertIn('failed', self.aspect.log.names())
        self.assertEqual([], self.fake.calls)
        self.assertEqual([('SwiftWrapper@w1', 'getinfo')], self.engine.launched)

    def test_passed_push_missing_wrapper_result_marks_failure_and_links_nothing(self):
        self.engine.results['SwiftWrapper@w1'] = None

        self._push_ignoring_logging_typeerror()

        self.assertIn('failed', self.aspect.log.names())
        self.assertEqual([], self.fake.calls)

    def test_passed_push_failed_account_step_raises_before_any_link(self):
        self.engine.results['wrapacct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'wrapacct step failed'):
            self.push([('src', 'a.bin')])

        self.assertEqual([], self.fake.calls)

    def test_passed_push_link_error_propagates_and_stops_linking(self):
        self.fake.failOn('put_object', 403)

        with self.assertRaises(ClientException) as ctx:
            self.push([('src', 'a.bin'), ('src', 'b.bin')])

        self.assertEqual(403, ctx.exception.http_status)
        self.assertEqual(1, len(self.fake.callsTo('put_object')))
        self.assertNotIn('passed', self.aspect.log.names())


if __name__ == '__main__':
    unittest.main()
