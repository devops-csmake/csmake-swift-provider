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
"""SwiftSoftLink: construction and manifest-link creation.

Before the migration SwiftSoftLink.__init__ had a line indented with a tab
among space-indented lines, which Python 3 rejects with TabError.  Here the
real constructor runs (with a minimal stand-in environment) and push() is
driven against an in-memory swift, including the dict iteration over the
matched objects.
"""
import types
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftSoftLink = swiftsupport.loadModule('SwiftSoftLink').SwiftSoftLink


def fakeEnvironment():
    """The few Environment attributes CsmakeModule.__init__ reads."""
    engine = swiftsupport.FakeEngine('unused')
    metadata = types.SimpleNamespace(getCurrent=lambda: {})
    return types.SimpleNamespace(engine=engine, metadata=metadata)


class TestSwiftSoftLink(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        for name in ('a.bin', 'b.bin', 'c.bin', 'd.bin'):
            self.fake.addObject('src', name, b'payload')
        self.fake.put_container('links')
        self.module = SwiftSoftLink(fakeEnvironment(), swiftsupport.RecordingLog())

    def push(self, **options):
        options.update({'account': 'acct', 'container': 'src',
                        'files': 'a.bin\nb.bin,c.bin'})
        with swiftsupport.patchConnection(self.fake):
            return self.module.push(options)

    def testPushCreatesManifestLinksForMatchedObjects(self):
        # setUp ran the real (formerly TabError) constructor
        self.assertEqual([], self.module._getPushedObjects())

        self.assertTrue(self.push(**{'to-container': 'links'}))

        self.assertEqual(
            [('src', 'a.bin'), ('src', 'b.bin'), ('src', 'c.bin')],
            self.module._getPushedObjects())
        puts = self.fake.callsTo('put_object')
        self.assertEqual(
            [('links', 'a.bin', None), ('links', 'b.bin', None),
             ('links', 'c.bin', None)],
            [args for args, _ in puts])
        for (container, name, _), kwargs in puts:
            headers = kwargs['headers']
            self.assertEqual('src/' + name, headers['X-Object-Manifest'])
            self.assertGreater(float(headers['X-Object-Meta-CreateTime']), 0)

    def testNoopRecordsObjectsButCreatesNoLinks(self):
        self.assertTrue(self.push())     # no to-container => noop

        self.assertEqual(3, len(self.module._getPushedObjects()))
        self.assertEqual([], self.fake.callsTo('put_object'))


if __name__ == '__main__':
    unittest.main()
