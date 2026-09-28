"""Explicit Remote method markers and service binding, without reflection stubs."""
import copy
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


def bind_typert_remote(service, service_key, options=None):
    namespace = (options or {}).get("namespace", service_key)
    wire_name("service key", service_key)
    wire_name("namespace", namespace)
    return MappingProxyType({"service": service, "serviceKey": service_key, "namespace": namespace})


class TypertRemoteService(Service):
    def __init__(self, ctx, service_key, options=None):
        super().__init__(ctx, service_key)
        self.typertRemote = bind_typert_remote(self, self.name, options)


def _decorate(method, invocation, mode=None, export=None):
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
    previous = _markers.get(method)
    if previous is not None and previous != marker:
        raise ValueError("Remote method has conflicting invocation markers")
    _markers[method] = marker
    return method


def Remote(option=None):
    if callable(option):
        return _decorate(option, {"kind": "direct"})
    def decorate(method):
        return _decorate(method, {"kind": "direct"},
                         option.get("mode") if isinstance(option, dict) else None,
                         option if isinstance(option, str) else None)
    return decorate


def RemoteScope(context, export=None):
    wire_name("Scope key", context)
    return lambda method: _decorate(method, {"kind": "context", "context": context}, export=export)


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
    return [dict(copy.deepcopy(marker), method=name) for name, marker in found.items()]


bindTypertRemote = bind_typert_remote
remoteMethods = remote_methods
