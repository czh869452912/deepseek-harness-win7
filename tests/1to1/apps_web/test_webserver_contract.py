"""
1:1 mapping of `reference/packages/host/webserver/tests/webserver.spec.ts`
(`@deepseek-ai/dsh-host-webserver`) — the carrier the served `apps/web` payload
rides.

Upstream cases:

  - ``applies gzip only to eligible socket-backed HTTP responses``
  - ``serves registered routes, index taps, and the fallback-seat semantics``
  - ``collects injection rows fresh per render and layers taps over the
    rendered rows``
  - ``fails the fiber when the port is already taken (fail-loud at activation)``

Both halves of the carrier are provided 1:1. The gzip middleware is the
reference's: `compression`/`compressionLevel`/`compressionThresholdBytes` with
the reference defaults, eligibility from the `compression` filter (no
content-range, never `text/event-stream`, a compressible content type), the
`Accept-Encoding` negotiation between `gzip` and `identity`, and the
`Vary: Accept-Encoding` mark the middleware leaves on every considered
response. Request-level upgrade dispatch is the reference listener: an exact
pathname match, a handler owning negotiation and the socket from its 101
onward, containment of handler and transport failures, and tracked upgraded
sockets closed with the server on teardown.
"""

import asyncio
import gzip
import inspect
import os
import re

import pytest

from dsh.cordis.context import Context
from dsh.host.frontend_static.frontend_static import decode_pathname
from dsh.host.webserver.injections import READY_MARKUP, render_index_injections
from dsh.host.webserver.webserver import WebServerPlugin, WebServerService


async def raw_request(port, path, method="GET"):
    """One real HTTP/1.1 request; returns (status, headers, body-text-window)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            ("%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" % (method, path)).encode("ascii")
        )
        await writer.drain()
        raw = await reader.read()
    finally:
        writer.close()
    if not raw:
        return None, {}, ""
    head_bytes, _, body = raw.partition(b"\r\n\r\n")
    status_line, _, raw_headers = head_bytes.partition(b"\r\n")
    status = int(status_line.split(b" ")[1])
    headers = {}
    for line in raw_headers.decode("latin-1").split("\r\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return status, headers, body.decode("utf-8", errors="replace")[:80]


async def start_server():
    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("web_server", server)
    await server.start()
    return server


async def http_request(port, path, accept_encoding=None, method="GET"):
    """
    One real HTTP/1.1 request; returns (status, headers, body).

    A gzip body is decompressed before it is returned, exactly as ``fetch``
    presents it, while the header table keeps the wire's `content-encoding`.
    """
    lines = ["%s %s HTTP/1.1" % (method, path), "Host: 127.0.0.1", "Connection: close"]
    if accept_encoding is not None:
        lines.append("Accept-Encoding: " + accept_encoding)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
        await writer.drain()
        raw = await reader.read()
    finally:
        writer.close()
    head_bytes, _, payload = raw.partition(b"\r\n\r\n")
    status_line, _, raw_headers = head_bytes.partition(b"\r\n")
    status = int(status_line.split(b" ")[1])
    headers = {}
    for line in raw_headers.decode("latin-1").split("\r\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    if headers.get("content-encoding") == "gzip":
        payload = gzip.decompress(payload)
    return status, headers, payload.decode("utf-8", errors="replace")


async def raw_upgrade(port, path):
    """Open one raw upgrade request and return after the handler writes its 101."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((
        "GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        "Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n" % path
    ).encode("ascii"))
    await writer.drain()
    data = await asyncio.wait_for(reader.read(4096), 5)
    assert b"101 Switching Protocols" in data, data
    return reader, writer


async def read_or_reset(reader, size=10):
    """Read one socket tail, treating a peer reset the way node reports close."""
    try:
        return await asyncio.wait_for(reader.read(size), 5)
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        return b""


@pytest.mark.asyncio
async def test_serves_registered_routes_index_taps_and_the_fallback_seat_semantics():
    server = await start_server()
    port = server.listened_port
    try:
        assert port > 0

        # Routing precedence: exact beats prefix, longest prefix wins, a prefix
        # route answers its own path, and routes own their method handling
        # (POST reaches a registered prefix; 405 is fallback-only semantics).
        async def exact(request, response):
            response.write_status(200)
            response.write_body(b"EXACT")
            await response.finish()

        async def api(request, response):
            response.write_status(200)
            response.write_body(b"API")
            await response.finish()

        async def deep(request, response):
            response.write_status(200)
            response.write_body(b"DEEP")
            await response.finish()

        server.register("exact", "/probe", exact)
        server.register("prefix", "/api", api)
        server.register("prefix", "/api/deep", deep)
        assert (await raw_request(port, "/probe"))[:1] == (200,)
        assert (await raw_request(port, "/probe"))[2] == "EXACT"
        assert (await raw_request(port, "/api/anything"))[2] == "API"
        assert (await raw_request(port, "/api/deep/leaf"))[2] == "DEEP"
        assert (await raw_request(port, "/api"))[2] == "API"
        assert (await raw_request(port, "/api/anything", method="POST"))[2] == "API"

        # Fallback seat: 404 while unclaimed; the owner answers everything no
        # named route matches; index taps are the owner's to apply; the seat
        # admits exactly one owner and the disposer releases it.
        assert (await raw_request(port, "/no/such/route"))[0] == 404
        untap = server.tap_index(lambda html: html.replace("<head>", "<head><script>window.__T__=1</script>"))
        assert "__T__" in server.apply_index_taps("<head></head>")

        async def fallback(request, response):
            # Decode like a real static server would — a malformed %-escape
            # throws here, probing the webserver's per-request error containment.
            decode_pathname(request.get("path") or "/")
            response.write_status(200)
            response.write_header("content-type", "text/html")
            response.write_body(server.apply_index_taps("<head></head><body>shell</body>").encode("utf-8"))
            await response.finish()

        release_fallback = server.register_fallback(fallback)
        with pytest.raises(ValueError, match="fallback already registered"):
            server.register_fallback(lambda request, response: None)
        assert "__T__" in (await raw_request(port, "/no/such/route"))[2]
        untap()
        assert "__T__" not in (await raw_request(port, "/no/such/route"))[2]
        assert "shell" in (await raw_request(port, "/no/such/route"))[2]

        # Per-request error containment: a malformed %-escape answers 400 and the
        # server keeps serving afterwards (no process-level failure path).
        assert (await raw_request(port, "/%zz"))[0] == 400
        assert (await raw_request(port, "/probe"))[2] == "EXACT"

        # Duplicate (kind, path) is a misconfiguration and throws; the disposer
        # restores registrability (register/disposer symmetry).
        with pytest.raises(ValueError, match="duplicate exact route"):
            server.register("exact", "/probe", lambda request, response: None)

        async def once(request, response):
            response.write_status(200)
            response.write_body(b"ONCE")
            await response.finish()

        dispose_once = server.register("exact", "/once", once)
        assert (await raw_request(port, "/once"))[2] == "ONCE"
        dispose_once()
        assert "shell" in (await raw_request(port, "/once"))[2]  # back to the fallback owner
        server.register("exact", "/once", lambda request, response: None)

        # Routes and requests use the pathname verbatim: the reference treats a
        # registered path as an absolute pathname without a trailing slash and
        # never rewrites either side, so `/probe/` is a different key that does
        # not answer `/probe` (and vice versa).
        async def trailing(request, response):
            response.write_status(200)
            response.write_body(b"TRAILING")
            await response.finish()

        assert server.match("/probe/") is None
        assert server.match("/probe") is not None
        dispose_trailing = server.register("exact", "/trailing/", trailing)
        assert (await raw_request(port, "/trailing/"))[2] == "TRAILING"
        assert "shell" in (await raw_request(port, "/trailing"))[2]  # not a match
        dispose_trailing()

        # Upgrade routes match exact pathnames, reject duplicate ownership, and
        # become registrable again after disposal. The accepted socket stays
        # open so the teardown assertion also covers upgraded-connection
        # ownership.
        upgraded_sockets = []

        async def events_upgrade(request, socket):
            assert request["path"] == "/events"
            upgraded_sockets.append(socket)
            socket.write(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n"
            )
            await socket.drain()

        dispose_upgrade = server.register_upgrade("/events", events_upgrade)
        with pytest.raises(ValueError, match="duplicate upgrade route"):
            server.register_upgrade("/events", lambda request, socket: None)
        upgraded_reader, upgraded_writer = await raw_upgrade(port, "/events?stream=mux")
        dispose_upgrade()
        server.register_upgrade("/events", lambda request, socket: None)

        # The upgrade table is keyed verbatim too: `/exact-only/` claims only
        # that pathname, and an upgrade to the trailing-slash-less spelling is
        # dispatched to no handler at all (destroyed without a response).
        async def exact_only(request, socket):
            socket.write(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n"
            )
            await socket.drain()

        dispose_exact_only = server.register_upgrade("/exact-only/", exact_only)
        exact_reader, exact_writer = await raw_upgrade(port, "/exact-only/")
        exact_writer.close()
        assert await read_or_reset(exact_reader) == b""
        missing_reader, missing_writer = await asyncio.open_connection("127.0.0.1", port)
        missing_writer.write(
            b"GET /exact-only HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n"
        )
        await missing_writer.drain()
        assert await read_or_reset(missing_reader) == b""
        missing_writer.close()
        dispose_exact_only()

        # The webserver contains raw-socket errors even before an upgrade
        # handler has installed its protocol implementation.
        async def failing_upgrade(request, socket):
            await asyncio.sleep(0)
            socket.transport.abort()

        server.register_upgrade("/upgrade-error", failing_upgrade)
        failed_reader, failed_writer = await asyncio.open_connection("127.0.0.1", port)
        failed_writer.write(
            b"GET /upgrade-error HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n"
        )
        await failed_writer.drain()
        assert await read_or_reset(failed_reader) == b""
        failed_writer.close()
        assert (await raw_request(port, "/probe"))[2] == "EXACT"

        # A handler that fails before writing its handshake is contained the
        # same way: the socket dies, the server keeps serving.
        async def raising_upgrade(request, socket):
            raise RuntimeError("test upgrade transport failure")

        server.register_upgrade("/upgrade-raises", raising_upgrade)
        raising_reader, raising_writer = await asyncio.open_connection("127.0.0.1", port)
        raising_writer.write(
            b"GET /upgrade-raises HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n"
        )
        await raising_writer.drain()
        assert await read_or_reset(raising_reader) == b""
        raising_writer.close()
        assert (await raw_request(port, "/probe"))[2] == "EXACT"

        # A path no upgrade route claims is destroyed without a response, and a
        # plain request to an upgrade path is answered by the ordinary router:
        # the upgrade table is consulted only for `Connection: Upgrade`.
        unclaimed_reader, unclaimed_writer = await asyncio.open_connection("127.0.0.1", port)
        unclaimed_writer.write(
            b"GET /no/such/upgrade HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Connection: Upgrade\r\nUpgrade: dsh-test\r\n\r\n"
        )
        await unclaimed_writer.drain()
        assert await read_or_reset(unclaimed_reader) == b""
        unclaimed_writer.close()
        assert "shell" in (await raw_request(port, "/no/such/upgrade"))[2]

        # Releasing the seat restores the unclaimed 404 and registrability.
        release_fallback()
        assert (await raw_request(port, "/no/such/route"))[0] == 404
        server.register_fallback(lambda request, response: None)

        # Teardown closes both ordinary and upgraded sockets before it resolves.
        await server.stop()
        assert upgraded_sockets[0].is_closing()
        assert await read_or_reset(upgraded_reader) == b""
        with pytest.raises(OSError):
            await raw_request(port, "/probe")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_collects_injection_rows_fresh_per_render_and_layers_taps_over_the_rendered_rows():
    server = await start_server()
    try:
        flag = {"value": "dark"}

        def inject(table):
            table.append({"kind": "script", "placement": "head", "text": "window.__Q__=1"})
            table.append({"kind": "script-src", "placement": "head", "src": '/plugins/a.js?rev="1"&x=<y>'})
            table.append({"kind": "script-preload", "src": '/plugins/b.js?rev="2"&x=<z>'})
            table.append({"kind": "global", "name": "__DSH_BOOT__", "value": {"rev": "</script><b>"}})
            table.append({"kind": "style", "text": "body{margin:0}"})
            table.append({"kind": "html", "placement": "head", "html": '<meta name="probe">'})
            table.append(
                {"kind": "script", "placement": "body", "text": 'window.__P__="%s"' % flag["value"]}
            )

        server.ctx.on("webserver/index-inject", inject)

        html = server.render_index("<html><head></head><body>shell</body></html>")
        # Head rows land right after the opening head tag in table order; the
        # body row lands after the opening body tag.
        order = [
            "<head>",
            "<script>window.__Q__=1</script>",
            '<script src="/plugins/a.js?rev=&quot;1&quot;&amp;x=&lt;y&gt;"></script>',
            '<link rel="preload" as="script" href="/plugins/b.js?rev=&quot;2&quot;&amp;x=&lt;z&gt;">',
            'globalThis["__DSH_BOOT__"] = {"rev":"\\u003c/script>\\u003cb>"}',
            "<style>body{margin:0}</style>",
            '<meta name="probe">',
            "<body>",
            '<script>window.__P__="dark"</script>',
            "shell",
        ]
        positions = [html.find(part) for part in order]
        assert all(at != -1 for at in positions), [
            part for part, at in zip(order, positions) if at == -1
        ]
        assert positions == sorted(positions)

        # Fresh collection per render: the listener reads live state at emit time.
        flag["value"] = "light"
        assert 'window.__P__="light"' in server.render_index("<head></head><body></body>")

        # Raw taps still run, over the already-rendered rows.
        untap = server.tap_index(lambda markup: markup.replace("window.__Q__=1", "window.__Q__=2"))
        assert "window.__Q__=2" in server.render_index("<head></head><body></body>")
        untap()

        # Tag-less fragments: head rows prepend, body rows append, and the
        # boot-readiness tail lands after the last body row. Upstream's tail is
        # `(globalThis.__DSH_BOOT_READY__ ??= Promise.withResolvers()).resolve()`;
        # this port spells the same deferred inline because no browser that runs
        # on Windows 7 provides `Promise.withResolvers`.
        rendered = render_index_injections(
            "<main>x</main>",
            [
                {"kind": "script", "placement": "head", "text": "H"},
                {"kind": "script", "placement": "body", "text": "B"},
            ],
        )
        assert rendered == "<script>H</script><main>x</main><script>B</script>" + READY_MARKUP
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_fails_the_fiber_when_the_port_is_already_taken():
    first = await start_server()
    taken_port = first.listened_port
    try:
        ctx = Context()
        second = WebServerService(ctx, host="127.0.0.1", port=taken_port)
        with pytest.raises(OSError):
            await second.start()
        # The first composition keeps serving the taken port.
        assert (await raw_request(taken_port, "/"))[0] == 404
        assert first._is_running is True
    finally:
        await first.stop()


@pytest.mark.asyncio
async def test_applies_gzip_only_to_eligible_socket_backed_http_responses():
    """
    The reference `Config` defaults and step validation, then the composed
    carrier with `compression: gzip` (level 1, threshold 16 bytes) answering
    eligible responses encoded and ineligible ones untouched.
    """
    assert WebServerService.resolve_config({"host": "127.0.0.1", "port": 0}) == {
        "host": "127.0.0.1",
        "port": 0,
        "compression": "none",
        "compressionLevel": 1,
        "compressionThresholdBytes": 1024,
    }
    with pytest.raises(ValueError):
        WebServerService.resolve_config({"host": "127.0.0.1", "port": 0, "compressionLevel": 10})

    ctx = Context()
    await ctx.plugin(
        WebServerPlugin,
        config={
            "host": "127.0.0.1",
            "port": 0,
            "compression": "gzip",
            "compressionLevel": 1,
            "compressionThresholdBytes": 16,
        },
    )
    server: WebServerService = ctx.get("web_server")
    assert server.compression == "gzip"
    await server.start()
    port = server.listened_port
    body = "compressible response " * 8
    raw_body = body.encode("utf-8")
    try:
        async def text(request, response):
            response.write_status(200)
            response.write_header("content-type", "text/plain; charset=utf-8")
            response.write_header("content-length", str(len(raw_body)))
            response.write_body(raw_body)
            await response.finish()

        async def stream(request, response):
            response.write_status(200)
            response.write_header("content-type", "application/json")
            await response.write_chunk(raw_body[:40])
            response.write_body(raw_body[40:])
            await response.finish()

        async def small(request, response):
            response.write_status(200)
            response.write_header("content-type", "text/plain")
            response.write_header("content-length", "5")
            response.write_body(b"small")
            await response.finish()

        async def events(request, response):
            response.write_status(200)
            response.write_header("content-type", "text/event-stream")
            response.write_body(raw_body)
            await response.finish()

        async def archive(request, response):
            response.write_status(200)
            response.write_header("content-type", "application/gzip")
            response.write_body(raw_body)
            await response.finish()

        async def ranged(request, response):
            response.write_status(206)
            response.write_header("content-type", "text/plain")
            response.write_header("content-range", "bytes 0-15/160")
            response.write_body(raw_body[:16])
            await response.finish()

        server.register("exact", "/text", text)
        server.register("exact", "/stream", stream)
        server.register("exact", "/small", small)
        server.register("exact", "/events", events)
        server.register("exact", "/archive", archive)
        server.register("exact", "/range", ranged)

        compressed = await http_request(port, "/text", accept_encoding="br, gzip, deflate")
        assert compressed[0] == 200
        assert compressed[2] == body
        assert compressed[1].get("content-encoding") == "gzip"
        assert "content-length" not in compressed[1]
        assert compressed[1].get("vary") == "Accept-Encoding"

        streamed = await http_request(port, "/stream", accept_encoding="gzip")
        assert streamed[2] == body
        assert streamed[1].get("content-encoding") == "gzip"

        small = await http_request(port, "/small", accept_encoding="gzip")
        assert "content-encoding" not in small[1]

        identity = await http_request(port, "/text", accept_encoding="gzip;q=0.5, identity;q=1")
        assert "content-encoding" not in identity[1]
        assert identity[1].get("vary") == "Accept-Encoding"

        # An absent `Accept-Encoding` negotiates identity: the negotiator parse
        # finds no acceptable token, so only the implicit identity entry matches.
        unmarked = await http_request(port, "/text")
        assert "content-encoding" not in unmarked[1]
        assert unmarked[2] == body

        for path in ("/events", "/archive", "/range"):
            excluded = await http_request(port, path, accept_encoding="gzip")
            assert "content-encoding" not in excluded[1], path
    finally:
        await server.stop()
