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
"""Shared test scaffolding for csmake-swift-provider.

There is no Swift or Keystone endpoint here, so the only thing faked is the
swiftclient connection (FakeSwift, an in-memory object store).  Everything
else -- SwiftProvider, the real CsmakeModule base-class helpers, real files
on disk, real threads -- is the production code.

CsmakeModule subclasses need a full engine to construct, so module methods
are driven on a bare instance (object.__new__) given just the attributes
the method touches: see makeModule().
"""
import hashlib
import importlib.util
import os
import sys
import types
import unittest.mock

from . import csmake_alias

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _installSwiftclientStub():
    """python-swiftclient is not a dependency of the test run: if it is not
    importable, register a minimal stand-in exposing what the repo uses."""
    if 'swiftclient' in sys.modules:
        return
    if importlib.util.find_spec('swiftclient') is not None:
        import swiftclient.client
        import swiftclient.exceptions
        return
    swiftclient = types.ModuleType('swiftclient')
    client = types.ModuleType('swiftclient.client')
    exceptions = types.ModuleType('swiftclient.exceptions')

    class ClientException(Exception):
        def __init__(self, msg, http_status=None, **kwargs):
            Exception.__init__(self, msg)
            self.http_status = http_status

    class Connection(object):
        def __init__(self, **kwargs):
            raise AssertionError("tests must patch swiftclient.client.Connection")

    exceptions.ClientException = ClientException
    client.Connection = Connection
    swiftclient.client, swiftclient.exceptions = client, exceptions
    sys.modules['swiftclient'] = swiftclient
    sys.modules['swiftclient.client'] = client
    sys.modules['swiftclient.exceptions'] = exceptions


def setup():
    """Call before importing anything from this repo.  May raise SkipTest."""
    csmake_alias.install()
    _installSwiftclientStub()
    if REPO not in sys.path:
        sys.path.insert(0, REPO)


def loadModule(name):
    """Load CsmakeModules/<name>.py by path (the directory is a namespace
    package that clashes with csmake core's own CsmakeModules otherwise)."""
    setup()
    modname = 'swift_provider_modules.' + name
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(REPO, 'CsmakeModules', name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[modname]
        raise
    return module


def swiftclientClientException():
    import swiftclient.exceptions
    return swiftclient.exceptions.ClientException


def patchConnection(fake):
    """Make swiftclient.client.Connection(**params) hand back `fake`."""
    import swiftclient.client
    return unittest.mock.patch.object(
        swiftclient.client, 'Connection', lambda **params: fake)


class RecordingLog(object):
    """Accepts every csmake log call (info, debug, devdebug, exception,
    passed, failed, ...) and remembers (name, args)."""
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *args, **kwargs: self.events.append((name, args))

    def names(self):
        return [name for name, _ in self.events]


class FakeEngine(object):
    """Just enough engine for SwiftProvider.getAccount(), resultsDir and
    CsmakeModule.__init__."""
    def __init__(self, resultsDir=None):
        self.resultsDir = resultsDir
        self.settings = {}
        self.clientParams = {'authurl': 'http://keystone.invalid/v3'}

    def launchStep(self, account, phase):
        value = (self.clientParams, {'account': 'acct', 'user': 'usr'})
        return types.SimpleNamespace(
            _didPass=lambda: True,
            _getReturnValue=lambda phase: value)


def makeModule(cls, engine, log=None):
    """A `cls` instance without running CsmakeModule.__init__ (which needs a
    whole csmake Environment).  Inherited helpers such as _fileMD5 and
    _ensureDirectoryExists are the real ones."""
    module = object.__new__(cls)
    module.engine = engine
    module.log = log if log is not None else RecordingLog()
    module.objects = []
    return module


class FakeSwift(object):
    """In-memory stand-in for swiftclient.client.Connection.

    Response headers are lower-cased, as swiftclient returns them.  Every
    mutating call is also appended to self.calls as (method, args, kwargs).
    get_object() streams *bytes* chunks of self.chunkSize, like swiftclient.
    """
    def __init__(self, chunkSize=7):
        self.containers = {}
        self.calls = []
        self.chunkSize = chunkSize

    def addObject(self, container, name, body=b'', **headers):
        ctr = self.containers.setdefault(
            container, {'headers': {'x-timestamp': '1.0'}, 'objects': {}})
        meta = {'x-timestamp': '1.0'}
        meta.update((k.lower(), v) for k, v in headers.items())
        ctr['objects'][name] = {'body': body, 'headers': meta}

    def _container(self, name):
        if name not in self.containers:
            raise swiftclientClientException()('Container GET failed', http_status=404)
        return self.containers[name]

    def _object(self, container, name):
        objects = self._container(container)['objects']
        if name not in objects:
            raise swiftclientClientException()('Object HEAD failed', http_status=404)
        return objects[name]

    def _record(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))

    def callsTo(self, method):
        return [(a, k) for m, a, k in self.calls if m == method]

    def get_account(self):
        return {}, [{'name': name} for name in self.containers]

    def get_container(self, container, **kwargs):
        ctr = self._container(container)
        listing = [{'name': name,
                    'hash': hashlib.md5(obj['body']).hexdigest(),
                    'bytes': len(obj['body'])}
                   for name, obj in ctr['objects'].items()]
        return dict(ctr['headers']), listing

    def head_container(self, container):
        return dict(self._container(container)['headers'])

    def head_object(self, container, name):
        obj = self._object(container, name)
        headers = dict(obj['headers'])
        headers['content-length'] = str(len(obj['body']))
        return headers

    def get_object(self, container, name, resp_chunk_size=None,
                   response_dict=None, headers=None):
        self._record('get_object', container, name)
        body = self._object(container, name)['body']
        chunks = (body[i:i + self.chunkSize]
                  for i in range(0, len(body), self.chunkSize))
        return self.head_object(container, name), chunks

    def put_container(self, container, headers=None, response_dict=None):
        self._record('put_container', container, headers)
        self.containers.setdefault(
            container, {'headers': {'x-timestamp': '1.0'}, 'objects': {}})

    def post_container(self, container, headers, response_dict=None):
        self._record('post_container', container, headers)

    def put_object(self, container, name, contents, **kwargs):
        self._record('put_object', container, name, contents, **kwargs)

    def post_object(self, container, name, headers=None):
        self._record('post_object', container, name, headers=headers)

    def delete_object(self, container, name):
        self._record('delete_object', container, name)
        del self._container(container)['objects'][name]

    def delete_container(self, container):
        self._record('delete_container', container)
        del self.containers[container]
