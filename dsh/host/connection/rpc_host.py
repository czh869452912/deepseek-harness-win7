"""Caller-owned Connection RPC channels, exact routes and JSON envelopes."""
import inspect
import json
import re
from types import SimpleNamespace

from dsh.cordis.service import Service
from dsh.cordis.json_text import stringify_json
from dsh.core.abort import NEVER_ABORTED
from dsh.host.connection.api_trust import is_trusted_api_request
from dsh.typert.artifact import UNDEFINED


def endpoint_from_path(channel, path):
    if not path.startswith(channel + "/"):
        return None
    endpoint = path[len(channel) + 1:]
    if any(part in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_$.-]+", part) for part in endpoint.split("/")):
        return None
    return endpoint


def response(status, body, headers=None):
    return {"status": status, "body": body, "headers": headers or {}}


def envelope(rpc_id, result):
    # An absent value is omitted on the wire; explicit null remains null.
    result = {key: value for key, value in result.items() if value is not UNDEFINED}
    return response(200, stringify_json({"type": "server-response", "rpcId": rpc_id, "result": result}), {"content-type": "application/json"})


async def rpc_fetch(channel, handler, request):
    endpoint = endpoint_from_path(channel, request["path"])
    if request.get("method") != "POST" or endpoint is None:
        return response(404, "not found")
    media = request.get("headers", {}).get("content-type", "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        return response(415, "content type must be application/json")
    try:
        body = json.loads(request.get("body", b""), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
    except (ValueError, TypeError, UnicodeError):
        return response(400, "body is not JSON")
    issues = []
    fields = {"type": "literal", "rpcId": "string", "method": "string"}
    for name, kind in fields.items():
        value = body.get(name, UNDEFINED) if isinstance(body, dict) else UNDEFINED
        if kind == "literal" and value != "client-request":
            issues.append({"code": "invalid_value", "values": ["client-request"], "path": [name], "message": 'Invalid input: expected "client-request"'})
        elif kind == "string" and not isinstance(value, str):
            received = "undefined" if value is UNDEFINED else "null" if value is None else "boolean" if type(value) is bool else "number" if type(value) in (int, float) else "array" if isinstance(value, list) else "object"
            issues.append({"expected": "string", "code": "invalid_type", "path": [name], "message": "Invalid input: expected string, received " + received})
    if not isinstance(body, dict):
        received = "null" if body is None else "array" if isinstance(body, list) else "string" if isinstance(body, str) else "boolean" if type(body) is bool else "number"
        issues = [{"expected": "object", "code": "invalid_type", "path": [], "message": "Invalid input: expected object, received " + received}]
    if issues:
        rpc_id = body.get("rpcId") if isinstance(body, dict) and isinstance(body.get("rpcId"), str) else "invalid-request"
        return envelope(rpc_id, {"ok": False, "error": {"code": "bad-request", "message": "invalid client-request message", "details": {"issues": issues}}})
    if body["method"] != endpoint:
        message = "method {} does not match endpoint {}".format(json.dumps(body["method"]), json.dumps(endpoint))
        return envelope(body["rpcId"], {"ok": False, "error": {"code": "bad-request", "message": message, "details": {"issues": []}}})
    try:
        result = handler(endpoint, body.get("payload", UNDEFINED), request.get("signal") or NEVER_ABORTED)
        if inspect.isawaitable(result):
            result = await result
        return envelope(body["rpcId"], result)
    except Exception as error:
        return response(500, "handler failure: " + str(error))


class HostConnectionService(Service):
    def __init__(self, ctx, trusted_hosts, browser_auth):
        super().__init__(ctx, "connection")
        self.trusted_hosts, self.browser_auth = list(trusted_hosts), browser_auth
        self.interceptors, self.fetch_routes = {}, {}
        self.__dict__.update(self._views(ctx))

    def _views(self, ctx):
        return {"rpc": SimpleNamespace(handle=lambda channel, handler: self.register(ctx, channel, handler),
                intercept=lambda channel, matches, handler: self.intercept(ctx, channel, matches, handler)),
                "fetch": SimpleNamespace(register=lambda route: self.register_fetch(ctx, route))}

    def _extend(self, props=None):
        props = dict(props or {})
        props.update(self._views(props.get("ctx", self.ctx)))
        return super()._extend(props)

    def request_rejection(self, request):
        if not is_trusted_api_request(request, self.trusted_hosts):
            return 403
        return None if self.browser_auth.is_authenticated(request) else 401

    requestRejection = request_rejection

    def authorize_index(self, request, response):
        return self.browser_auth.authorize_index(request, response)

    authorizeIndex = authorize_index

    def authenticated_url(self, base_url):
        return self.browser_auth.authenticated_url(base_url)

    authenticatedUrl = authenticated_url

    def intercept(self, owner, channel, matches, handler):
        if channel != "/api":
            raise ValueError("connection: invalid shared RPC channel")
        entry = {"matches": matches, "handler": handler}
        def setup():
            if channel in self.interceptors:
                raise ValueError("connection: shared RPC channel already has an interceptor")
            self.interceptors[channel] = entry
            return lambda: self.interceptors.pop(channel, None)
        return owner.effect(setup, "Connection rpc interceptor")

    def register_fetch(self, owner, route):
        if endpoint_from_path("/api", route["path"]) is None:
            raise ValueError("connection: invalid exact Fetch route")
        if not route["methods"] or len(set(route["methods"])) != len(route["methods"]):
            raise ValueError("connection: exact Fetch route requires unique methods")
        entry = {"methods": set(route["methods"]), "fetch": route["fetch"]}
        def setup():
            if route["path"] in self.fetch_routes:
                raise ValueError("connection: exact Fetch route already registered")
            self.fetch_routes[route["path"]] = entry
            return lambda: self.fetch_routes.pop(route["path"], None)
        return owner.effect(setup, "Connection Fetch route")

    def create_shared_fetch_handler(self, channel):
        async def fetch(request):
            route = self.fetch_routes.get(request["path"])
            if route is not None and request["method"] in route["methods"]:
                value = route["fetch"](request)
                return await value if inspect.isawaitable(value) else value
            endpoint = endpoint_from_path(channel, request["path"])
            interceptor = self.interceptors.get(channel)
            if endpoint is None or interceptor is None or not interceptor["matches"](endpoint):
                return response(404, "not found")
            return await rpc_fetch(channel, interceptor["handler"], request)
        return SimpleNamespace(fetch=fetch)

    createSharedFetchHandler = create_shared_fetch_handler

    def register(self, owner, channel, handler):
        if channel == "/api" or not re.fullmatch(r"/[A-Za-z0-9._~-]+", channel):
            raise ValueError("connection: invalid or reserved RPC channel")
        from dsh.host.connection.http_bridge import bridge_handler
        async def fetch(request):
            return await rpc_fetch(channel, handler, request)
        return owner.effect(lambda: owner.get("webServer").register("prefix", channel, bridge_handler(self, fetch)), "Connection rpc channel")
