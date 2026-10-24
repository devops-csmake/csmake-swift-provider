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
"""SwiftCleanupContainers: remove dangling object links and empty containers.

Walks account -> containers -> objects with dict.items() (iteritems() is gone
in Python 3), deleting links whose x-object-manifest target no longer exists
and then any container left empty.  The swift connection and csmake engine
are mocked; each scenario scripts one situation on the fake account.
"""
import unittest

from . import swiftsupport

swiftsupport.setup()
SwiftCleanupContainers = swiftsupport.loadModule(
    'SwiftCleanupContainers').SwiftCleanupContainers
ClientException = swiftsupport.swiftclientClientException()


class CleanupTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = swiftsupport.FakeSwift()
        self.engine = swiftsupport.FakeEngine()
        self.module = swiftsupport.makeModule(SwiftCleanupContainers, self.engine)

    def link(self, container, name, manifest):
        self.fake.addObject(container, name, b'', **{'x-object-manifest': manifest})

    def push(self, containers='links'):
        with swiftsupport.patchConnection(self.fake):
            return self.module.push({'account': 'acct', 'containers': containers})

    def deleted(self):
        return [a for a, _ in self.fake.callsTo('delete_object')]

    def deletedContainers(self):
        return [a[0] for a, _ in self.fake.callsTo('delete_container')]


class TestDanglingLinks(CleanupTestCase):
    def setUp(self):
        CleanupTestCase.setUp(self)
        self.fake.addObject('gone', 'unrelated.bin', b'x')   # target container
        self.fake.addObject('links', 'plain.txt', b'text')   # keeps 'links' alive

    def test_push_deletes_link_whose_target_is_gone(self):
        self.link('links', 'dangling.bin', 'gone/dangling.bin')

        self.assertTrue(self.push())

        self.assertEqual([('links', 'dangling.bin')], self.deleted())

    def test_push_keeps_link_whose_target_exists(self):
        self.fake.addObject('data', 'real.bin', b'payload')
        self.link('links', 'live.bin', 'data/real.bin')

        self.push()

        self.assertEqual([], self.deleted())

    def test_push_keeps_link_whose_target_has_segment_objects(self):
        # a dynamic large object: the manifest prefix matches its segments
        self.fake.addObject('data', 'big.bin/000001', b'seg')
        self.link('links', 'big.bin', 'data/big.bin/')

        self.push()

        self.assertEqual([], self.deleted())

    def test_push_skips_manifest_without_container_delimiter(self):
        self.link('links', 'malformed.bin', 'no-container-delimiter')

        self.push()

        self.assertEqual([], self.deleted())
        self.assertTrue(any('not well formed' in m
                            for m in self.module.log.messages('info')))

    def test_push_leaves_plain_objects_alone(self):
        self.push()

        self.assertEqual([], self.deleted())
        self.assertEqual({'plain.txt'}, set(self.fake.containers['links']['objects']))

    def test_push_keeps_container_that_still_has_objects(self):
        self.link('links', 'dangling.bin', 'gone/dangling.bin')

        self.push()

        self.assertEqual([], self.deletedContainers())

    def test_push_marks_step_passed(self):
        self.assertTrue(self.push())

        self.assertEqual(['passed'], self.module.log.names()[-1:])


class TestEmptyContainers(CleanupTestCase):
    def test_push_removes_container_emptied_by_link_removal(self):
        self.fake.addObject('gone', 'unrelated.bin', b'x')
        self.link('links', 'dangling.bin', 'gone/dangling.bin')

        self.push()

        self.assertEqual([('links', 'dangling.bin')], self.deleted())
        self.assertEqual(['links'], self.deletedContainers())

    def test_push_removes_container_that_was_already_empty(self):
        self.fake.addContainer('links')

        self.push()

        self.assertEqual(['links'], self.deletedContainers())

    def test_push_only_touches_containers_matching_the_pattern(self):
        self.fake.addContainer('links-old')
        self.fake.addContainer('other')

        self.push(containers='links-*')

        self.assertEqual(['links-old'], self.deletedContainers())

    def test_push_containers_option_accepts_newline_and_comma_separators(self):
        for name in ('a', 'b', 'c', 'd'):
            self.fake.addContainer(name)

        self.push(containers='a\nb,c')

        self.assertEqual({'a', 'b', 'c'}, set(self.deletedContainers()))


class TestFailures(CleanupTestCase):
    def test_push_failed_account_step_raises_before_any_swift_call(self):
        self.engine.results['acct'] = swiftsupport.stepResult(passed=False)

        with self.assertRaisesRegex(ValueError, 'acct step failed'):
            self.push()

        self.assertEqual([], self.fake.calls)

    def test_push_head_error_propagates_and_deletes_nothing(self):
        self.fake.addObject('links', 'plain.txt', b'text')
        self.fake.failOn('head_object', 500)

        with self.assertRaises(ClientException):
            self.push()

        self.assertEqual([], self.deleted())
        self.assertNotIn('passed', self.module.log.names())

    def test_push_link_delete_error_propagates(self):
        self.fake.addObject('gone', 'unrelated.bin', b'x')
        self.link('links', 'dangling.bin', 'gone/dangling.bin')
        self.fake.failOn('delete_object', 403)

        with self.assertRaises(ClientException):
            self.push()

        self.assertEqual([], self.deletedContainers())

    def test_push_container_delete_error_propagates(self):
        self.fake.addContainer('links')
        self.fake.failOn('delete_container', 409)

        with self.assertRaises(ClientException) as ctx:
            self.push()

        self.assertEqual(409, ctx.exception.http_status)


if __name__ == '__main__':
    unittest.main()
