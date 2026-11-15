"""Explicit Remote method markers and service binding, without reflection stubs."""
import weakref
from types import MappingProxyType

from dsh.cordis.service import Service
from dsh.typert.stores import wire_name

_markers = weakref.WeakKeyDictionary()


class TypertLookupFailure(Exception):
    def __init__(self, failure):
        super().__init__("Typert lookup policy rejected the requested identity")
        self.failure = failure


class TypertRemoteFailure(Exception):
    def __init__(self, failure):
        super().__init__(failure["message"])
        self.failure = failure


class RemoteError(Exception):
    """Shared, structurally identified rc.1 Remote failure."""
    isDSHRemoteError = True
    name = 'RemoteError'

    def __init__(self, code, message, details, cause=None):
        super().__init__(message)
        self.code, self.message, self.details, self.cause = code, message, details, cause
        self.failure = dict(code=code, message=message, details=details)


def remote_error_of(value):
    if getattr(value, 'isDSHRemoteError', None) is True and isinstance(getattr(value, 'code', None), str):
        return dict(code=value.code, message=str(value), details=value.details)
    return None


def bind_typert_remote(service, service_key, options=None):
    namespace = (options or {}).get("namespace", service_key)
    wire_name("service key", service_key)
    wire_name("namespace", namespace)
    from dsh.cordis.context import Context
    ctx = getattr(service, 'ctx', None)
    if isinstance(ctx, Context) and 'invocation' not in ctx.root.reflect.props:
        ctx.root.reflect.accessor('invocation', dict(get=lambda *_:None))
    return MappingProxyType({"service": service, "serviceKey": service_key, "namespace": namespace})


class TypertRemoteService(Service):
    def __init__(self, ctx, service_key, options=None):
        super().__init__(ctx, service_key)
        self.typertRemote = bind_typert_remote(self, self.name, options)


def _decorate(method, invocation, mode=None, export=None, resources=None):
    if not callable(method) or method.__name__.startswith("_"):
        raise TypeError("Remote decorators require public instance methods")
    if export is not None:
        wire_name("Remote export name", export)
    marker = {"invocation": invocation}
    if mode is not None:
        if mode != "stream":
            raise ValueError("Remote mode must be stream")
        marker["mode"] = mode
    if export is not None and export != method.__name__:
        marker["exportName"] = export
    if resources is not None:
        marker['resources'] = resources
    previous = _markers.get(method)
    if previous is not None and (previous != marker or previous.get('resources') is not resources):
        raise ValueError("Remote method has conflicting invocation markers")
    _markers[method] = marker
    return method


def _options(option, scoped=False):
    requirement = 'RemoteScope options require name or resources' if scoped else 'Remote options require name, mode: "stream", or resources'
    accepted = {'name', 'resources'} if scoped else {'name', 'mode', 'resources'}
    if not isinstance(option, dict) or not option or set(option) - accepted or 'mode' in option and option['mode'] != 'stream':
        raise TypeError('typert-protocol: ' + requirement)
    resources = None
    if 'resources' in option:
        source = option['resources']
        if not isinstance(source, dict):
            raise TypeError('typert-protocol: Remote resources require at least one reader')
        readers = {}
        for kind, reader in source.items():
            if not callable(reader):
                raise TypeError('typert-protocol: Remote resource reader "%s" must be a function' % kind)
            readers[kind] = reader
        if not readers:
            raise TypeError('typert-protocol: Remote resources require at least one reader')
        resources = MappingProxyType(readers)
    return option.get('mode'), option.get('name'), resources


def Remote(option=None):
    if callable(option):
        return _decorate(option, {"kind": "direct"})
    mode, export, resources = _options(option) if option is not None and not isinstance(option, str) else (None, option, None)
    return lambda method: _decorate(method, {"kind": "direct"}, mode, export, resources)


def RemoteScope(context, export=None):
    wire_name("Scope key", context)
    mode, export, resources = _options(export, True) if isinstance(export, dict) else (None, export, None)
    return lambda method: _decorate(method, {"kind": "context", "context": context}, export=export, resources=resources)


def remote_methods(service):
    found = {}
    for cls in reversed(type(service).__mro__):
        for name, method in cls.__dict__.items():
            if callable(method) and method in _markers:
                marker = _markers[method]
                previous = found.get(name)
                if previous is not None and previous != marker:
                    raise ValueError("Remote method has conflicting inherited markers")
                found[name] = marker
    return [dict(marker, invocation=dict(marker['invocation']), method=name) for name, marker in found.items()]


bindTypertRemote = bind_typert_remote
remoteMethods = remote_methods
