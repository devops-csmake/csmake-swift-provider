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
"""Test-only shim: make 'from Csmake.X import Y' resolve to CsmakeCore.

Plugin modules import their base classes from 'Csmake', but the installed
csmake only ships 'CsmakeCore'.  That mismatch is a known ecosystem issue
outside this repo, so tests alias it here instead of touching production
imports.  Csmake.<sub> resolves to the very same module object as
CsmakeCore.<sub>.  Looks for CsmakeCore on sys.path, then in the sibling
'csmake' checkout; raises unittest.SkipTest when neither exists.
"""
import importlib
import importlib.abc
import importlib.util
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, real):
        self.real, self.realSpec = real, real.__spec__

    def create_module(self, spec):
        return self.real

    def exec_module(self, module):
        module.__spec__ = self.realSpec  # undo the import system's re-stamp


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith('Csmake.'):
            return None
        realname = 'CsmakeCore.' + fullname[len('Csmake.'):]
        try:
            real = importlib.import_module(realname)
        except ModuleNotFoundError as e:
            if e.name == realname:
                return None
            raise
        return importlib.util.spec_from_loader(fullname, _AliasLoader(real))


def install():
    if importlib.util.find_spec('Csmake') is not None:
        return
    if importlib.util.find_spec('CsmakeCore') is None:
        sibling = os.path.join(os.path.dirname(_REPO), 'csmake')
        if not os.path.isdir(os.path.join(sibling, 'CsmakeCore')):
            raise unittest.SkipTest("csmake core not found")
        sys.path.insert(0, sibling)
    sys.modules['Csmake'] = importlib.import_module('CsmakeCore')
    if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())
