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
"""SwiftAccount and KeystoneAccount: build the swiftclient connection
parameters from step options.  Pure option handling -- no swift traffic."""
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftAccount = swiftsupport.loadModule('SwiftAccount').SwiftAccount
KeystoneAccount = swiftsupport.loadModule('KeystoneAccount').KeystoneAccount

NON_ASCII = 'caf\N{LATIN SMALL LETTER E WITH ACUTE}-\N{LATIN SMALL LETTER U WITH DIAERESIS}ser'


def run(cls, **extra):
    options = {'user': 'alice', 'account': 'proj',
               'service': 'http://auth.example'}
    options.update(extra)
    module = swiftsupport.makeModule(cls, swiftsupport.FakeEngine())
    return module, module.default(options), options


class TestSwiftAccount(unittest.TestCase):
    def test_default_builds_swift_v1_auth_url_and_retry_policy(self):
        module, (client, _), _ = run(SwiftAccount)

        self.assertEqual({
            'authurl': 'http://auth.example:8080/auth/v1.0',
            'user': 'proj:alice',
            'insecure': True,
            'retries': 10,
            'starting_backoff': 15,
            'max_backoff': 90}, client)

    def test_default_returns_the_options_alongside_the_client(self):
        module, (client, returnedOptions), options = run(SwiftAccount)

        self.assertIs(options, returnedOptions)
        self.assertEqual(['passed'], module.log.names()[-1:])

    def test_default_honours_port_path_and_version_overrides(self):
        _, (client, _), _ = run(SwiftAccount, **{
            'service-port': '443', 'service-path': 'v2/auth',
            'service-version': '2.0'})

        self.assertEqual('http://auth.example:443/v2/auth/v2.0', client['authurl'])

    def test_default_password_becomes_the_key(self):
        _, (client, _), _ = run(SwiftAccount, password='s3cret')

        self.assertEqual('s3cret', client['key'])

    def test_default_without_password_has_no_key(self):
        _, (client, _), _ = run(SwiftAccount)

        self.assertNotIn('key', client)

    def test_default_keeps_non_ascii_account_and_user(self):
        _, (client, _), _ = run(SwiftAccount, user=NON_ASCII, account=NON_ASCII)

        self.assertEqual('%s:%s' % (NON_ASCII, NON_ASCII), client['user'])

    def test_every_phase_returns_the_account(self):
        # CsmakeModuleAllPhase routes any phase name to default()
        module = swiftsupport.makeModule(SwiftAccount, swiftsupport.FakeEngine())
        options = {'user': 'u', 'account': 'a', 'service': 'http://s'}

        client, _ = module.push(options)

        self.assertEqual('a:u', client['user'])


class TestKeystoneAccount(unittest.TestCase):
    def test_default_builds_keystone_v3_auth_url_and_retry_policy(self):
        _, (client, _), _ = run(KeystoneAccount)

        self.assertEqual({
            'authurl': 'http://auth.example:35357/v3',
            'user': 'proj:alice',
            'insecure': True,
            'retries': 10,
            'starting_backoff': 15,
            'max_backoff': 90,
            'auth_version': '3'}, client)

    def test_default_honours_port_and_version_overrides(self):
        _, (client, _), _ = run(KeystoneAccount, **{
            'service-port': '5000', 'service-version': '2'})

        self.assertEqual('http://auth.example:5000/v2', client['authurl'])
        self.assertEqual('2', client['auth_version'])

    def test_default_password_becomes_the_key(self):
        _, (client, _), _ = run(KeystoneAccount, password='s3cret')

        self.assertEqual('s3cret', client['key'])

    def test_default_without_password_has_no_key(self):
        _, (client, _), _ = run(KeystoneAccount)

        self.assertNotIn('key', client)

    def test_default_returns_the_options_alongside_the_client(self):
        module, (_, returnedOptions), options = run(KeystoneAccount)

        self.assertIs(options, returnedOptions)
        self.assertEqual(['passed'], module.log.names()[-1:])

    def test_default_keeps_non_ascii_account_and_user(self):
        _, (client, _), _ = run(KeystoneAccount, user=NON_ASCII, account=NON_ASCII)

        self.assertEqual('%s:%s' % (NON_ASCII, NON_ASCII), client['user'])


if __name__ == '__main__':
    unittest.main()
