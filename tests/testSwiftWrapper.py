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
"""SwiftWrapper: ensure the release-wrapper container and advertise it.

The swift connection and csmake engine are mocked; failures are scripted on
the fake connection (403 on create, ...) and on the account steps.
"""
import types
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftWrapper = swiftsupport.loadModule('SwiftWrapper').SwiftWrapper
ClientException = swiftsupport.swiftclientClientException()


class WrapperTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.engine = swiftsupport.FakeEngine(phase='prep')
        self.env = types.SimpleNamespace(env={})
        self.module = swiftsupport.makeModule(
            SwiftWrapper, self.engine, env=self.env,
            calledId='SwiftWrapper@release')

    def run_(self, method, **options):
        options.setdefault('account', 'acct')
        options.setdefault('container', 'wrap')
        with swiftsupport.patchConnection(self.fake):
            return getattr(self.module, method)(options)


class TestPrep(WrapperTestCase):
    def test_prep_creates_missing_wrapper_container(self):
        self.run_('prep')

        self.assertEqual(['get_container', 'put_container'], self.fake.methodsCalled())
        self.assertEqual([(('wrap', {}), {})], self.fake.callsTo('put_container'))

    def test_prep_leaves_existing_wrapper_container_alone(self):
        self.fake.addContainer('wrap')

        self.run_('prep')

        self.assertEqual(['get_container'], self.fake.methodsCalled())

    def test_prep_authenticates_with_the_current_engine_phase(self):
        self.run_('prep')

        self.assertEqual([('acct', 'prep')], self.engine.launched)

    def test_prep_returns_container_and_account_and_registers_wrapper(self):
        result = self.run_('prep')

        self.assertEqual(('wrap', 'acct'), result)
        self.assertEqual({'__wrapper__release': 'Exists'}, self.env.env)
        self.assertEqual(['passed', 'passed'], self.module.log.names()[-2:])

    def test_prep_access_grants_read_to_every_reader(self):
        self.engine.accounts['readerA'] = ({}, {'account': 'pA', 'user': 'uA'})
        self.engine.accounts['readerB'] = ({}, {'account': 'pB', 'user': 'uB'})
        self.engine.accounts['readerC'] = ({}, {'account': 'pC', 'user': 'uC'})

        self.run_('prep', access='readerA, readerB\nreaderC')

        self.assertEqual(
            [(('wrap', {'X-Container-Read': 'pA:uA,pB:uB,pC:uC'}), {})],
            self.fake.callsTo('post_container'))
        self.assertEqual(
            [('acct', 'prep'), ('readerA', 'prep'), ('readerB', 'prep'),
             ('readerC', 'prep')], self.engine.launched)

    def test_prep_without_access_posts_no_acl(self):
        self.run_('prep')

        self.assertEqual([], self.fake.callsTo('post_container'))

    def test_prep_failed_account_step_raises_and_touches_nothing(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.run_('prep')

        self.assertEqual([], self.fake.calls)
        self.assertEqual({}, self.env.env)

    def test_prep_missing_account_result_raises(self):
        self.engine.results['acct'] = None

        with self.assertRaises(ValueError):
            self.run_('prep')

    def test_prep_container_create_forbidden_propagates_without_registering(self):
        self.fake.failOn('put_container', 403)

        with self.assertRaises(ClientException) as ctx:
            self.run_('prep')

        self.assertEqual(403, ctx.exception.http_status)
        self.assertEqual({}, self.env.env)
        self.assertNotIn('passed', self.module.log.names())

    def test_prep_failed_reader_step_raises_before_setting_acl(self):
        self.engine.results['readerA'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'readerA step failed'):
            self.run_('prep', access='readerA')

        self.assertEqual([], self.fake.callsTo('post_container'))


class TestDefaultAndGetinfo(WrapperTestCase):
    def test_default_registers_marker_under_the_id_after_the_at_sign(self):
        self.module.calledId = 'SwiftWrapper@nightly'

        result = self.run_('default')

        self.assertEqual(('wrap', 'acct'), result)
        self.assertEqual({'__wrapper__nightly': 'Exists'}, self.env.env)

    def test_default_registers_marker_for_plain_id(self):
        self.module.calledId = 'nightly'

        self.run_('default')

        self.assertEqual({'__wrapper__nightly': 'Exists'}, self.env.env)

    def test_default_never_talks_to_swift(self):
        self.run_('default')

        self.assertEqual([], self.fake.calls)
        self.assertEqual([], self.engine.launched)

    def test_getinfo_returns_container_and_account_without_registering(self):
        result = self.run_('getinfo')

        self.assertEqual(('wrap', 'acct'), result)
        self.assertEqual({}, self.env.env)
        self.assertEqual(['passed'], self.module.log.names())

    def test_any_other_phase_just_reports_the_wrapper(self):
        # CsmakeModuleAllPhase routes unknown phases to default()
        result = self.run_('package')

        self.assertEqual(('wrap', 'acct'), result)
        self.assertIn('__wrapper__release', self.env.env)


if __name__ == '__main__':
    unittest.main()
