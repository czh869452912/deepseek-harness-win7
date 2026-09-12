"""
1:1 mapping of `reference/packages/host/frontend-static/tests/frontend-static.spec.ts`
(`@deepseek-ai/dsh-host-frontend-static`), the served form of the built
`@deepseek-ai/dsh-web-frontend` payload this unit ships.

Upstream case:

  - ``serves explicit index entries and files while preserving HTTP error
    semantics``

The upstream case is a REAL-composition test: a cordis.yml booted through the
vendored Loader mounts the credentials store, the webserver, the connection row
and the frontend row, and every assertion observes the served HTTP surface —
authenticated index entry points with index taps, asset serving with MIME types,
empty 404 misses, traversal rejection, 405 on non-GET/HEAD, the 400 guard for a
malformed path, and seat release on fiber disposal (HMR safety).

This port drives the same seats over a real socket: `WebServerService` +
`CredentialsLocalPlugin` + `ConnectionPlugin` + `FrontendStaticPlugin`, with a
temporary dist fixture identical to the upstream one.
"""

import asyncio
import os

import pytest

from dsh.cordis.context import Context
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.host.connection.connection import ConnectionPlugin
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.webserver.webserver import WebServerService

INDEX_BODY = "<head></head><body>shell</body>"
APP_JS = "export {}"
MANIFEST = "{}"


async def raw_request(port, path, method="GET", cookie=None):
    """
    One real HTTP/1.1 request; returns (status, headers, body-text-window).

    The upstream window is 200 bytes, wide enough to keep the index body markers
    visible behind its served prelude. This port's boot-readiness tail spells the
    deferred inline instead of `Promise.withResolvers` (unavailable to every
    browser that runs on Windows 7), so the same markers sit behind a longer
    prelude and the window is widened to keep them visible.
    """
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        head = "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\n" % (method, path)
        if cookie is not None:
            head += "Cookie: %s\r\n" % cookie
        writer.write((head + "Connection: close\r\n\r\n").encode("ascii"))
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
    return status, headers, body.decode("utf-8", errors="replace")[:600]


async def load_composition(tmp_path):
    """Write the upstream dist fixture and boot the authenticated served seats."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(INDEX_BODY, encoding="utf-8")
    (dist / "app.js").write_text(APP_JS, encoding="utf-8")
    (dist / "blob.bin").write_text("BLOB", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text(MANIFEST, encoding="utf-8")
    (dist / "empty").mkdir()

    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("web_server", server)
    ctx.plugin(CredentialsLocalPlugin, config={"path": str(tmp_path / ".credentials.yaml"), "watch": False})
    ctx.plugin(ConnectionPlugin)
    frontend = ctx.plugin(
        FrontendStaticPlugin,
        config={"distIndex": str(dist / "index.html")},
    )
    await server.start()
    return ctx, server, frontend, str(dist)


async def authenticated_cookie(port, ctx):
    """Perform the process-token exchange and return the browser-session cookie."""
    launch = ctx.get("connection").authenticated_url("http://127.0.0.1:%d" % port)
    status, headers, _ = await raw_request(port, "/?token=" + launch.split("token=", 1)[1])
    assert status == 303
    assert headers.get("location") == "/"
    assert headers.get("set-cookie")
    return headers["set-cookie"].split(";", 1)[0]


@pytest.mark.asyncio
async def test_serves_explicit_index_entries_and_files_while_preserving_http_error_semantics(tmp_path):
    ctx, server, frontend, dist = await load_composition(tmp_path)
    port = server.listened_port
    try:
        # An unauthenticated index request is refused with the minimal notice
        # every index request shares.
        status, headers, body = await raw_request(port, "/")
        assert status == 401
        assert headers.get("content-type") == "text/plain; charset=utf-8"
        assert body == "dsh web authentication required; reopen the URL printed by dsh web.\n"

        cookie = await authenticated_cookie(port, ctx)

        # Real assets with their MIME types; a live rebuild is served on the
        # next read.
        status, headers, body = await raw_request(port, "/app.js", cookie=cookie)
        assert (status, headers.get("content-type"), body) == (200, "text/javascript; charset=utf-8", APP_JS)
        status, headers, body = await raw_request(port, "/manifest.webmanifest", cookie=cookie)
        assert (status, headers.get("content-type"), body) == (200, "application/manifest+json", MANIFEST)
        status, headers, body = await raw_request(port, "/app.js", method="HEAD", cookie=cookie)
        assert (status, headers.get("content-type"), body) == (200, "text/javascript; charset=utf-8", "")
        with open(os.path.join(dist, "app.js"), "w", encoding="utf-8") as handle:
            handle.write("export const rebuilt = true")
        status, _, body = await raw_request(port, "/app.js", cookie=cookie)
        assert (status, body) == (200, "export const rebuilt = true")

        # Unknown extension ships as octet-stream.
        status, headers, body = await raw_request(port, "/blob.bin", cookie=cookie)
        assert (status, headers.get("content-type"), body) == (200, "application/octet-stream", "BLOB")

        # Only the root and index path render index.html through registered taps.
        untap = server.tap_index(
            lambda html: html.replace("<head>", "<head><script>window.__T__=1</script>")
        )
        for path in ("/", "/index.html", "/?fixture"):
            status, headers, body = await raw_request(port, path, cookie=cookie)
            assert status == 200, path
            assert headers.get("content-type") == "text/html; charset=utf-8", path
            assert "__T__" in body, path
            assert "shell" in body, path
        status, headers, body = await raw_request(port, "/", method="HEAD", cookie=cookie)
        assert (status, headers.get("content-type"), body) == (200, "text/html; charset=utf-8", "")
        untap()
        assert "__T__" not in (await raw_request(port, "/", cookie=cookie))[2]

        # A missing configured index follows the same empty-404 contract for both
        # of its public entry paths and for both supported methods.
        os.remove(os.path.join(dist, "index.html"))
        for path in ("/", "/index.html"):
            get = await raw_request(port, path, cookie=cookie)
            head = await raw_request(port, path, method="HEAD", cookie=cookie)
            assert (get[0], get[1].get("content-type"), get[2]) == (404, None, ""), path
            assert head == get, path

        # Ordinary unknown paths and static-resource misses are empty 404s for
        # both GET and HEAD; neither class can be mistaken for the HTML shell.
        ordinary_misses = ["/no/such/route", "/empty", "/app.js/child"]
        asset_misses = [
            "/missing.js",
            "/missing.css",
            "/missing.mjs",
            "/missing.js.map",
            "/missing.webmanifest",
            "/missing.manifest",
        ]
        for path in ordinary_misses + asset_misses:
            get = await raw_request(port, path, cookie=cookie)
            head = await raw_request(port, path, method="HEAD", cookie=cookie)
            assert (get[0], get[1].get("content-type"), get[2]) == (404, None, ""), path
            assert head == get, path

        # Traversal outside the dist root is 403, non-GET/HEAD is 405, and a
        # malformed filesystem target still reaches the webserver's 400 guard.
        assert (await raw_request(port, "/..%2f..%2fetc%2fpasswd", cookie=cookie))[0] == 403
        assert (await raw_request(port, "/app.js", method="POST", cookie=cookie))[0] == 405
        assert (await raw_request(port, "/bad%00path", cookie=cookie))[0] == 400

        # HMR safety: disposing the frontend row releases the fallback seat (the
        # unclaimed webserver answers 404) and the seat is claimable again.
        disposal = frontend.dispose()
        if asyncio.iscoroutine(disposal):
            await disposal
        assert server._fallback is None
        assert (await raw_request(port, "/no/such/route"))[0] == 404
        server.register_fallback(lambda request, response: None)
    finally:
        await server.stop()
