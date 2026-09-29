"""Carrier-independent strict/SRC Remote invocation and cancellation boundary."""
import asyncio
import inspect
import json
import math
from collections.abc import Mapping

from dsh.core.abort import NEVER_ABORTED
from dsh.typert.artifact import UNDEFINED
from dsh.typert.remote import TypertLookupFailure, TypertRemoteFailure, remote_methods
from dsh.typert.stores import field, resolve_async


class TypertGatewayError(Exception):
    def __init__(self, code, endpoint, message, field=None):
        super().__init__("typert gateway: " + endpoint + ": " + message)
        self.code, self.endpoint, self.field = code, endpoint, field


class RemoteInvocationCancelled(Exception):
    pass


def original_of(receiver):
    return getattr(receiver, "cordis.original", getattr(receiver, "_original", receiver))


def binding_of(receiver, service_key, endpoint, namespace=None):
    original = original_of(receiver)
    binding = getattr(original, "typertRemote", None)
    if not isinstance(binding, Mapping) or binding.get("service") is not original or binding.get("serviceKey") != service_key or not isinstance(binding.get("namespace"), str) or namespace is not None and binding["namespace"] != namespace:
        raise TypertGatewayError("binding-invalid", endpoint, "Service has no consistent typertRemote binding")
    return binding


def assert_json(value, ancestors=None):
    if value is None or type(value) in (str, bool):
        return
    if type(value) in (int, float):
        if math.isfinite(value):
            return
        raise ValueError("non-finite number is not JSON-safe")
    if type(value) not in (dict, list):
        raise ValueError("non-plain value is not JSON-safe")
    ancestors = set() if ancestors is None else ancestors
    if id(value) in ancestors:
        raise ValueError("cyclic value is not JSON-safe")
    ancestors.add(id(value))
    try:
        if isinstance(value, dict) and any(type(key) is not str for key in value):
            raise ValueError("object keys must be strings")
        for item in value.values() if isinstance(value, dict) else value:
            assert_json(item, ancestors)
    finally:
        ancestors.remove(id(value))


def decode(codec, value, endpoint, key):
    try:
        if codec["mode"] == "strict":
            value = field(codec["schema"], "parse")(value)
            if value is UNDEFINED:
                return value
        assert_json(value)
        return value
    except Exception as error:
        raise TypertGatewayError("input-invalid", endpoint, "wire field %s failed boundary validation" % json.dumps(key, ensure_ascii=False), key) from error


def exact_arguments(args, descriptor, endpoint):
    if type(args) is not dict:
        raise TypertGatewayError("arguments-invalid", endpoint, "args must be a plain object")
    expected = {row["wire"] for row in descriptor["parameters"]}
    if descriptor["invocation"]["kind"] == "context":
        expected.add(descriptor["invocation"]["wire"])
    omissible = {row["wire"] for row in descriptor["parameters"] if row["source"] == "json" and (row.get("acceptsUndefined") is True or row["codec"]["mode"] == "src-json")}
    extra = [key for key in args if key not in expected]
    missing = [row['wire'] for row in descriptor['parameters'] if row['wire'] not in args and row['wire'] not in omissible]
    if descriptor['invocation']['kind'] == 'context' and descriptor['invocation']['wire'] not in args:
        missing.append(descriptor['invocation']['wire'])
    clauses = []
    if missing:
        clauses.append('missing ' + ', '.join(json.dumps(key, ensure_ascii=False) for key in missing))
    if extra:
        clauses.append('unexpected ' + ', '.join(json.dumps(str(key), ensure_ascii=False) for key in extra))
    if clauses:
        raise TypertGatewayError("arguments-invalid", endpoint, "args fields do not match the descriptor: " + '; '.join(clauses))


def remote_request(endpoint, payload, signal):
    parts = endpoint.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("invalid Remote endpoint")
    if type(payload) is not dict or set(payload) != {"args"} or type(payload["args"]) is not dict:
        raise ValueError("Remote payload must contain exactly one plain-object args field")
    return {"namespace": parts[0], "method": parts[1], "args": payload["args"], "signal": signal}


def rpc_failure(error):
    if isinstance(error, RemoteInvocationCancelled):
        failure = {"code": "cancelled", "message": str(error), "details": {}}
    elif isinstance(error, (TypertLookupFailure, TypertRemoteFailure)):
        failure = error.failure
    else:
        failure = {"code": "internal", "message": str(error), "details": {}}
    return {"ok": False, "error": failure}


class RemoteDispatcher:
    def __init__(self, ctx):
        self.ctx = ctx

    def _services(self):
        for key, definition in list(self.ctx.reflect.props.items()):
            if definition.type == "service":
                receiver = self.ctx.get(key)
                if receiver is not None:
                    yield key, receiver

    def claims_endpoint(self, endpoint):
        parts = endpoint.split("/")
        if len(parts) != 2 or not all(parts):
            return False
        registry = self.ctx.get("typert")
        if registry.local.get(endpoint) is not None or registry.local.hasSeen(endpoint):
            return True
        for _, receiver in self._services():
            original = original_of(receiver)
            binding = getattr(original, "typertRemote", None)
            if isinstance(binding, Mapping) and binding.get("namespace") == parts[0]:
                if any(row.get("exportName", row["method"]) == parts[1] for row in remote_methods(original)):
                    return True
        return False

    def descriptor(self, namespace, method, endpoint):
        registry = self.ctx.get("typert")
        strict = registry.local.get(endpoint)
        if strict is not None:
            return strict
        if registry.local.hasSeen(endpoint):
            raise TypertGatewayError("definition-unavailable", endpoint, "strict definition was withdrawn and SRC fallback is forbidden")
        candidates = []
        for key, receiver in self._services():
            original = original_of(receiver)
            if getattr(original, "typertRemote", None) is None:
                continue
            binding = binding_of(receiver, key, endpoint)
            if binding["namespace"] != namespace:
                continue
            marker = next((row for row in remote_methods(original) if row.get("exportName", row["method"]) == method), None)
            if marker is not None:
                candidates.append(self.src_descriptor(binding, marker, method, endpoint))
        if not candidates:
            raise TypertGatewayError("invocation-unavailable", endpoint, "no active Remote method exports this endpoint")
        if len(candidates) > 1:
            raise TypertGatewayError("ambiguous-endpoint", endpoint, "multiple active Services export this endpoint")
        return candidates[0]

    def src_descriptor(self, binding, marker, method, endpoint):
        implementation = getattr(type(binding["service"]), marker["method"], None)
        if not inspect.isfunction(implementation):
            raise TypertGatewayError("method-unavailable", endpoint, "Remote marker has no instance method")
        signature = list(inspect.signature(implementation).parameters.values())
        signature = signature[1:]  # Python's explicit self is not a business argument.
        if any(row.kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD) or row.default is not inspect.Parameter.empty for row in signature):
            raise TypertGatewayError("signature-invalid", endpoint, "SRC method requires identifier parameters without defaults or rest")
        names = [row.name for row in signature]
        cancellation = "signal" in names
        if cancellation and names[-1] != "signal":
            raise TypertGatewayError("signature-invalid", endpoint, "signal must be the final parameter", "signal")
        parameters, wires = [], set()
        registry = self.ctx.get("typert")
        for name in names[:-1] if cancellation else names:
            matches = [row for row in registry.lookups.definitions() if row.parameter == name]
            if len(matches) > 1:
                raise TypertGatewayError("signature-invalid", endpoint, "parameter matches multiple lookup providers", name)
            row = {"name": name, "wire": name, "source": "json", "codec": {"mode": "src-json"}}
            if matches:
                row.update(wire=matches[0].wire, source="lookup", lookup=matches[0].key)
            if row["wire"] in wires:
                raise TypertGatewayError("signature-invalid", endpoint, "multiple parameters use the same wire field", row["wire"])
            wires.add(row["wire"])
            parameters.append(row)
        invocation = {"kind": "direct"}
        if marker["invocation"]["kind"] == "context":
            key = marker["invocation"]["context"]
            provider = registry.contexts.getHost(key)
            if provider is None:
                raise TypertGatewayError("context-unavailable", endpoint, "Context provider unavailable")
            if field(provider, "wire") in wires:
                raise TypertGatewayError("signature-invalid", endpoint, "Context identity conflicts with wire field", field(provider, "wire"))
            invocation = {"kind": "context", "context": key, "wire": field(provider, "wire"), "codec": {"mode": "src-json"}}
        row = {"id": "src:" + binding["serviceKey"] + "#" + endpoint, "service": binding["serviceKey"],
               "namespace": binding["namespace"], "method": method, "invocation": invocation,
               "parameters": parameters, "result": {"mode": "src-json"}}
        if marker["method"] != method:
            row["implementation"] = marker["method"]
        if "mode" in marker:
            row["mode"] = marker["mode"]
        if cancellation:
            row["cancellation"] = {"parameter": "signal"}
        return row

    async def _resolve(self, provider, codec, value, wire, endpoint, kind):
        if provider is None:
            raise TypertGatewayError(kind + "-unavailable", endpoint, kind + " provider unavailable", wire)
        if field(provider, "wire") != wire or codec["mode"] == "strict" and field(provider, "wireTypeSymbol") != codec["typeSymbol"]:
            raise TypertGatewayError("provider-mismatch", endpoint, kind + " provider does not match its definition", wire)
        try:
            resolved = await resolve_async(field(provider, "resolve"), value)
        except TypertLookupFailure:
            raise
        except Exception as error:
            raise TypertGatewayError(kind + "-failed", endpoint, kind + " provider failed", wire) from error
        if resolved is None:
            raise TypertGatewayError(kind + "-not-found", endpoint, kind + " identity not found", wire)
        return resolved

    async def prepare(self, request):
        endpoint = request["namespace"] + "/" + request["method"]
        row = self.descriptor(request["namespace"], request["method"], endpoint)
        args = request["args"]
        exact_arguments(args, row, endpoint)
        context = self.ctx
        invocation = row["invocation"]
        registry = self.ctx.get("typert")
        if invocation["kind"] == "context":
            provider = registry.contexts.getHost(invocation["context"])
            # Context provider presence/matching precedes input decoding.
            if provider is None:
                raise TypertGatewayError("context-unavailable", endpoint, "Context provider unavailable")
            if field(provider, "wire") != invocation["wire"] or invocation["codec"]["mode"] == "strict" and field(provider, "wireTypeSymbol") != invocation["codec"]["typeSymbol"]:
                raise TypertGatewayError("provider-mismatch", endpoint, "Context provider does not match its definition", invocation["wire"])
            value = decode(invocation["codec"], args[invocation["wire"]], endpoint, invocation["wire"])
            context = await self._resolve(provider, invocation["codec"], value, invocation["wire"], endpoint, "context")
        receiver = context.get(row["service"])
        if receiver is None:
            raise TypertGatewayError("service-unavailable", endpoint, "active Service is unavailable")
        binding_of(receiver, row["service"], endpoint, row["namespace"])
        async def parameter(item):
            wire = item["wire"]
            if wire not in args:
                return UNDEFINED
            value = decode(item["codec"], args[wire], endpoint, wire)
            if item["source"] == "json":
                return value
            return await self._resolve(registry.lookups.get(item["lookup"]), item["codec"], value, wire, endpoint, "lookup")
        positional = list(await asyncio.gather(*(parameter(item) for item in row["parameters"])))
        if "cancellation" in row:
            positional.append(request.get("signal") or NEVER_ABORTED)
        method = getattr(receiver, row.get("implementation", row["method"]), None)
        if not callable(method):
            raise TypertGatewayError("method-unavailable", endpoint, "active Service has no callable method")
        return endpoint, row, method, positional

    async def invoke(self, request):
        endpoint, row, method, args = await self.prepare(request)
        if row.get("mode") == "stream":
            raise TypertGatewayError("signature-invalid", endpoint, "stream Remote methods require the stream carrier")
        try:
            result = method(*args)
            return await result if inspect.isawaitable(result) else result
        except Exception as error:
            if getattr(request.get("signal"), "aborted", False):
                raise RemoteInvocationCancelled("Remote invocation was aborted: " + endpoint) from error
            raise

    async def stream(self, request):
        endpoint, row, method, args = await self.prepare(request)
        if row.get("mode") != "stream":
            raise TypertGatewayError("signature-invalid", endpoint, "unary Remote methods cannot use the stream carrier")
        try:
            source = method(*args)
        except Exception as error:
            if getattr(request.get("signal"), "aborted", False):
                raise RemoteInvocationCancelled("Remote invocation was aborted: " + endpoint) from error
            raise
        if not hasattr(source, "__aiter__") and not hasattr(source, "__iter__") or isinstance(source, (str, bytes, dict)):
            raise TypertGatewayError("result-invalid", endpoint, "stream method did not return an iterable", "result")
        return cancellable_stream(source, endpoint, request.get("signal") or NEVER_ABORTED)


async def cancellable_stream(source, endpoint, signal):
    iterator = source.__aiter__() if hasattr(source, "__aiter__") else iter(source)
    aborted = asyncio.create_task(signal.wait_aborted())
    pending = None
    try:
        while True:
            if signal.aborted:
                raise RemoteInvocationCancelled("Remote invocation was aborted: " + endpoint)
            if hasattr(iterator, "__anext__"):
                pending = asyncio.ensure_future(iterator.__anext__())
                await asyncio.wait((pending, aborted), return_when=asyncio.FIRST_COMPLETED)
                if signal.aborted:
                    raise RemoteInvocationCancelled("Remote invocation was aborted: " + endpoint)
                try:
                    value = await pending
                except StopAsyncIteration:
                    return
            else:
                try:
                    value = next(iterator)
                except StopIteration:
                    return
            yield value
    finally:
        aborted.cancel()
        if pending is not None and not pending.done():
            pending.cancel()
        await asyncio.gather(*([aborted, pending] if pending is not None else [aborted]), return_exceptions=True)
        close = getattr(iterator, "aclose", None) or getattr(iterator, "close", None)
        if close:
            value = close()
            if inspect.isawaitable(value):
                await value
