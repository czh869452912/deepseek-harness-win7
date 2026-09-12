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

The gzip case is MISSING: this port has no response-compression provider (the
shipped Web composition configures `compression: gzip`, and the port's Config
carries no compression keys), which is tracked as its own provider task rather
than restated as a weaker assertion.

The upgrade half of the second case is MISSING as request-level behaviour: the
port keeps `register_upgrade` registrations with the reference's duplicate
ownership rule, but its HTTP loop never dispatches `Connection: Upgrade` to
them (the shipped Web surface uses SSE, not WebSocket). The registration and
disposal assertions are ported; the 101 handshake is not faked.
"""

import asyncio
import inspect
import os
import re

import pytest

from dsh.cordis.context import Context
from dsh.host.frontend_static.frontend_static import decode_pathname
from dsh.host.webserver.injections import READY_MARKUP, render_index_injections
from dsh.host.webserver.webserver import WebServerService


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

        # Releasing the seat restores the unclaimed 404 and registrability.
        release_fallback()
        assert (await raw_request(port, "/no/such/route"))[0] == 404
        server.register_fallback(lambda request, response: None)

        # Upgrade routes reject duplicate ownership and become registrable again
        # after disposal. (Request-level upgrade dispatch is a recorded gap: the
        # port's HTTP loop never performs the 101 handshake.)
        dispose_upgrade = server.register_upgrade("/events", lambda request, socket: None)
        with pytest.raises(ValueError, match="duplicate upgrade route"):
            server.register_upgrade("/events", lambda request, socket: None)
        dispose_upgrade()
        server.register_upgrade("/events", lambda request, socket: None)
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


def test_gzip_response_compression_is_not_provided():
    """
    Recorded absence, not a weaker assertion.

    Upstream `Config` defaults `compression: 'none'` and the shipped Web
    composition sets `gzip` (level 1, threshold 1024 bytes), with the webserver
    owning the response encoding. This port's carrier has no compression keys at
    all, so the official gzip case has no counterpart; adding the provider is a
    separate task and must not be faked here.
    """
    service = WebServerService(Context(), host="127.0.0.1", port=0)
    assert not hasattr(service, "compression")
    assert not hasattr(service, "_gzip")
