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
"""Guard: no production module may import the retired 'Csmake' package.

csmake core renamed 'Csmake' to 'CsmakeCore'.  A plugin that still says
'from Csmake.X import Y' cannot be loaded by a current csmake.  Static check
only (parses source, imports nothing), so it needs no csmake core installed.
"""
import ast
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = ('.git', '__pycache__', 'tests')


def _production_python_files():
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith('.py'):
                yield os.path.join(dirpath, name)


def _imported_roots(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.lineno, node.module or ''
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name


class TestNoLegacyCsmakeImports(unittest.TestCase):

    def test_no_module_imports_the_retired_csmake_package(self):
        offenders = []
        for path in _production_python_files():
            with open(path, 'rb') as source:
                tree = ast.parse(source.read(), path)
            for lineno, name in _imported_roots(tree):
                if name == 'Csmake' or name.startswith('Csmake.'):
                    offenders.append('%s:%d imports %s' % (
                        os.path.relpath(path, REPO), lineno, name))
        self.assertEqual(
            [], offenders,
            "import from CsmakeCore, not the retired Csmake package")


if __name__ == '__main__':
    unittest.main()
