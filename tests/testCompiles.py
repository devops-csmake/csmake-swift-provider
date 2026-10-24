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
"""Every Python file in the repo must compile under Python 3.

Catches Python-2-only syntax (print statements, 'except X, e'), and the
mixed tab/space indentation that Python 3 rejects with TabError (it was
present in SwiftSoftLink.__init__ before the migration).  Needs no csmake
core, so it runs everywhere.
"""
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pythonFiles():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__')]
        for name in files:
            if name.endswith('.py'):
                yield os.path.join(root, name)


class TestCompiles(unittest.TestCase):
    def test_compile_every_python_file(self):
        files = sorted(_pythonFiles())
        self.assertTrue(files, "no python files found under %s" % REPO)
        for path in files:
            with self.subTest(file=os.path.relpath(path, REPO)):
                with open(path, 'rb') as source:
                    compile(source.read(), path, 'exec')


if __name__ == '__main__':
    unittest.main()
