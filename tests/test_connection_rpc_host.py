import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.host.connection.rpc_host import HostConnectionService, rpc_fetch
from dsh.host.connection.http_bridge import bridge_handler
from dsh.host.webserver.webserver import WebServerService
from dsh.typert.artifact import UNDEFINED


def request(body, method="POST", content_type="application/json"):
    return {"path": "/api/test/run", "method": method, "headers": {"content-type": content_type}, "body": json.dumps(body).encode()}


@pytest.mark.asyncio
async def test_rpc_envelopes_method_fence_and_absent_result():
    calls = []
    async def handler(endpoint, payload, signal):
        calls.append((endpoint, payload))
        return {"ok": True, "value": UNDEFINED}
    valid = {"type": "client-request", "rpcId": "id", "method": "test/run", "payload": {"args": {}}}
    result = await rpc_fetch("/api", handler, request(valid))
    assert json.loads(result["body"]) == {"type": "server-response", "rpcId": "id", "result": {"ok": True}}
    for body in ({"rpcId": "known"}, dict(valid, method="other")):
        result = await rpc_fetch("/api", handler, request(body))
        assert result["status"] == 200
        assert json.loads(result["body"])["result"]["error"]["code"] == "bad-request"
    assert len(calls) == 1
    assert (await rpc_fetch("/api", handler, request(valid, content_type="text/plain")))["status"] == 415
    assert (await rpc_fetch("/api", handler, request(valid, method="GET")))["status"] == 404


class Owner(Plugin):
    inject = ["connection"]
    def apply(self, ctx):
        self.bound = ctx.get("connection")


@pytest.mark.asyncio
async def test_fetch_priority_and_interceptor_are_owned_by_reading_fiber():
    ctx = Context()
    connection = HostConnectionService(ctx, [], SimpleNamespace(is_authenticated=lambda _: True))
    fiber = await ctx.plugin(Owner)
    calls = []
    async def rpc(endpoint, payload, signal):
        calls.append(endpoint)
        return {"ok": True, "value": 1}
    try:
        fiber.plugin.bound.rpc.intercept("/api", lambda _: True, rpc)
        fiber.plugin.bound.fetch.register({"path": "/api/test/run", "methods": ["GET"], "fetch": lambda _: {"status": 202, "body": "exact"}})
        fetch = connection.createSharedFetchHandler("/api").fetch
        assert (await fetch(request({}, method="GET")))["status"] == 202
        assert (await fetch(request({"type": "client-request", "rpcId": "r", "method": "test/run"})))["status"] == 200
        assert calls == ["test/run"]
        with pytest.raises(ValueError, match="already has"):
            connection.rpc.intercept("/api", lambda _: True, rpc)
        await fiber.dispose()
        assert (await fetch(request({}, method="GET")))["status"] == 404
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_http_bridge_rejects_before_body_and_bounds_chunked_reads():
    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    auth = {"allowed": True}
    connection = SimpleNamespace(request_rejection=lambda _: None if auth["allowed"] else 401)
    async def fetch(request):
        return {"status": 200, "body": request["body"]}
    server.register("prefix", "/api", bridge_handler(connection, fetch, limit=8))
    await server.start()
    async def exchange(headers, body=b""):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.listened_port)
        try:
            writer.write(b"POST /api/test HTTP/1.1\r\nHost: 127.0.0.1\r\n" + headers + b"\r\n" + body)
            await writer.drain()
            return await asyncio.wait_for(reader.read(), 1)
        finally:
            writer.close()
            await writer.wait_closed()
    try:
        # No body supplied: rejection must not wait for the advertised length.
        assert b" 413 " in await exchange(b"Content-Length: 1000000\r\n")
        auth["allowed"] = False
        assert b" 401 " in await exchange(b"Content-Length: 4\r\n")
        auth["allowed"] = True
        valid = await exchange(b"Transfer-Encoding: chunked\r\n", b"3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n")
        assert valid.endswith(b"abcde")
        assert b" 413 " in await exchange(b"Transfer-Encoding: chunked\r\n", b"9\r\n")
    finally:
        await server.stop()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_socket_disconnect_aborts_the_borrowed_handler_signal():
    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    entered, stopped = asyncio.Event(), asyncio.Event()
    async def fetch(request):
        entered.set()
        await request["signal"].wait_aborted()
        stopped.set()
        return {"status": 200, "body": "done"}
    server.register("prefix", "/api", bridge_handler(SimpleNamespace(request_rejection=lambda _: None), fetch))
    await server.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", server.listened_port)
    try:
        writer.write(b"POST /api/test HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        await entered.wait()
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(stopped.wait(), 1)
    finally:
        writer.close()
        await server.stop()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_connection_owns_api_authentication_and_releases_route():
    from dsh.host.connection.canonical import CanonicalConnectionPlugin
    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("webServer", server)
    records = {}
    def modify(key, mutator):
        changed = mutator(records.get(key))
        if changed is not None:
            records[key] = changed
        return records[key]
    ctx.set_service("credentials", SimpleNamespace(modify_record=modify))
    fiber = await ctx.plugin(CanonicalConnectionPlugin)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.listened_port)
        writer.write(b"POST /api/test/run HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 999999\r\n\r\n")
        await writer.drain()
        assert b" 401 " in await asyncio.wait_for(reader.read(), 1)
        writer.close()
        await writer.wait_closed()
        await fiber.dispose()
        assert ctx.get("connection") is None and server.match("/api/test/run") is None
    finally:
        await server.stop()
        await ctx.fiber.dispose()
