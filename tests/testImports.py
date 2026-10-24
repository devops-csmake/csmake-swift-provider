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
"""Each plugin module must import under Python 3.

compile() (testCompiles.py) proves the syntax is valid; this proves the
module-level code also runs: imports resolve (e.g. 'urllib.parse'), class
bodies evaluate.  Skips if csmake core is not found.
"""
import glob
import os
import unittest

from . import swiftsupport

swiftsupport.setup()


class TestImports(unittest.TestCase):
    def testEveryPluginModuleImports(self):
        paths = sorted(glob.glob(
            os.path.join(swiftsupport.REPO, 'CsmakeModules', '*.py')))
        self.assertTrue(paths)
        for path in paths:
            name = os.path.basename(path)[:-len('.py')]
            with self.subTest(module=name):
                module = swiftsupport.loadModule(name)
                self.assertTrue(hasattr(module, name),
                                "%s.py should define class %s" % (name, name))

    def testSwiftProviderLibraryImports(self):
        from CsmakeSwiftProvider.SwiftProvider import SwiftProvider
        self.assertTrue(callable(SwiftProvider.getContainerListing))


if __name__ == '__main__':
    unittest.main()
