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

These are unit tests: the swiftclient connection (FakeSwift), the csmake
engine (FakeEngine) and the file mapping (FakeMapping) are the mocked
boundaries, with scriptable failures.  Everything else -- SwiftProvider, the
real CsmakeModule base-class helpers -- is production code.  Real temp files
are used only where file open mode is the behaviour under test.

The fakes honour swiftclient's type contract: object bodies stream as
*bytes* chunks, header names come back lower-cased, header values are str.

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

    def messages(self, name):
        """The formatted text of every `name` event."""
        return [args[0] % args[1:] if args else '' for n, args in self.events
                if n == name]


def stepResult(passed=True, value=None):
    """What engine.launchStep() returns for a step."""
    return types.SimpleNamespace(
        _didPass=lambda: passed, _getReturnValue=lambda phase: value)


class FakeEngine(object):
    """The csmake engine as seen by the swift modules.

    launchStep() hands back an account step result: (clientParams, account)
    from self.accounts[step] if scripted, else a default.  Script failures
    with self.results[step] = stepResult(passed=False) or None.
    Every call is recorded in self.launched as (step, phase).
    """
    def __init__(self, resultsDir=None, phase='push'):
        self.resultsDir = resultsDir
        self.settings = {}
        self.phase = phase
        self.clientParams = {'authurl': 'http://keystone.invalid/v3'}
        self.accounts = {}
        self.results = {}
        self.launched = []

    def getPhase(self):
        return self.phase

    def launchStep(self, step, phase, extraOptions=None, overrideOptions=None):
        self.launched.append((step, phase))
        if step in self.results:
            return self.results[step]
        value = self.accounts.get(
            step, (self.clientParams, {'account': 'acct', 'user': 'usr'}))
        return stepResult(True, value)


class FakeMapping(object):
    """csmake's file mapping: iterspecs() yields (froms, tos), each a list
    of {'relLocation': ..., 'location': ...} dicts."""
    def __init__(self, *specs):
        self.specs = specs

    def iterspecs(self):
        return iter(self.specs)


def makeModule(cls, engine, log=None, **attributes):
    """A `cls` instance without running CsmakeModule.__init__ (which needs a
    whole csmake Environment).  Inherited helpers such as _fileMD5 and
    _ensureDirectoryExists are the real ones."""
    module = object.__new__(cls)
    module.engine = engine
    module.log = log if log is not None else RecordingLog()
    module.objects = []
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


def fixedTime(now):
    """Stand-in for a module's `time` import whose time() is `now`."""
    return types.SimpleNamespace(time=lambda: now, sleep=lambda seconds: None)


class FakeSwift(object):
    """In-memory stand-in for swiftclient.client.Connection.

    Every call is appended to self.calls as (method, args, kwargs); use
    callsTo(method).  Script failures with failOn() / failStream().
    put_object() consumes a file-like `contents` the way swiftclient does and
    keeps what it read in self.uploaded[(container, name)].
    """
    def __init__(self, chunkSize=7):
        self.containers = {}
        self.calls = []
        self.chunkSize = chunkSize
        self.failures = []
        self.streamFailures = {}
        self.uploaded = {}
        self.uploadModes = {}

    # -- scripting ---------------------------------------------------
    def addObject(self, container, name, body=b'', **headers):
        ctr = self.containers.setdefault(
            container, {'headers': {'x-timestamp': '1.0'}, 'objects': {}})
        meta = {'x-timestamp': '1.0'}
        meta.update((k.lower(), v) for k, v in headers.items())
        ctr['objects'][name] = {'body': body, 'headers': meta}

    def addContainer(self, container, **headers):
        ctr = self.containers.setdefault(
            container, {'headers': {'x-timestamp': '1.0'}, 'objects': {}})
        ctr['headers'].update((k.lower(), v) for k, v in headers.items())

    def failOn(self, method, status=500, container=None, name=None, exc=None):
        """Make `method` raise (ClientException(http_status=status) unless
        `exc`), optionally only for one container and/or object."""
        if exc is None:
            exc = swiftclientClientException()(
                '%s failed' % method, http_status=status)
        self.failures.append((method, container, name, exc))

    def failStream(self, container, name, afterChunks, exc):
        """get_object()'s iterator raises `exc` after `afterChunks` chunks."""
        self.streamFailures[(container, name)] = (afterChunks, exc)

    # -- internals ---------------------------------------------------
    def _begin(self, method, args, kwargs, container=None, name=None):
        self.calls.append((method, args, kwargs))
        for m, c, n, exc in self.failures:
            if m == method and c in (None, container) and n in (None, name):
                raise exc

    def _container(self, name):
        if name not in self.containers:
            raise swiftclientClientException()(
                'Container %s not found' % name, http_status=404)
        return self.containers[name]

    def _object(self, container, name):
        objects = self._container(container)['objects']
        if name not in objects:
            raise swiftclientClientException()(
                'Object %s not found' % name, http_status=404)
        return objects[name]

    def callsTo(self, method):
        return [(a, k) for m, a, k in self.calls if m == method]

    def methodsCalled(self):
        return [m for m, _, _ in self.calls]

    # -- swiftclient.client.Connection API ---------------------------
    def get_account(self):
        self._begin('get_account', (), {})
        return {}, [{'name': name} for name in self.containers]

    def get_container(self, container, **kwargs):
        self._begin('get_container', (container,), kwargs, container)
        ctr = self._container(container)
        listing = [{'name': name,
                    'hash': hashlib.md5(obj['body']).hexdigest(),
                    'bytes': len(obj['body'])}
                   for name, obj in ctr['objects'].items()]
        return dict(ctr['headers']), listing

    def head_container(self, container):
        self._begin('head_container', (container,), {}, container)
        return dict(self._container(container)['headers'])

    def head_object(self, container, name):
        self._begin('head_object', (container, name), {}, container, name)
        obj = self._object(container, name)
        headers = dict(obj['headers'])
        headers['content-length'] = str(len(obj['body']))
        return headers

    def get_object(self, container, name, resp_chunk_size=None,
                   response_dict=None, headers=None):
        self._begin('get_object', (container, name),
                    {'resp_chunk_size': resp_chunk_size,
                     'headers': headers}, container, name)
        obj = self._object(container, name)
        body = obj['body']
        failure = self.streamFailures.get((container, name))

        chunks = [body[i:i + self.chunkSize]
                  for i in range(0, len(body), self.chunkSize)]

        def stream():
            for count, chunk in enumerate(chunks):
                if failure is not None and count == failure[0]:
                    raise failure[1]
                yield chunk
            if failure is not None and failure[0] >= len(chunks):
                raise failure[1]
        resultHeaders = dict(obj['headers'])
        resultHeaders['content-length'] = str(len(body))
        return resultHeaders, stream()

    def put_container(self, container, headers=None, response_dict=None):
        self._begin('put_container', (container, headers), {}, container)
        self.containers.setdefault(
            container, {'headers': {'x-timestamp': '1.0'}, 'objects': {}})

    def post_container(self, container, headers, response_dict=None):
        self._begin('post_container', (container, headers), {}, container)

    def put_object(self, container, name, contents, **kwargs):
        self._begin('put_object', (container, name, contents), kwargs,
                    container, name)
        if hasattr(contents, 'read'):
            self.uploadModes[(container, name)] = getattr(contents, 'mode', None)
            self.uploaded[(container, name)] = contents.read()

    def post_object(self, container, name, headers=None):
        self._begin('post_object', (container, name),
                    {'headers': headers}, container, name)

    def delete_object(self, container, name):
        self._begin('delete_object', (container, name), {}, container, name)
        del self._container(container)['objects'][name]

    def delete_container(self, container):
        self._begin('delete_container', (container,), {}, container)
        del self.containers[container]
