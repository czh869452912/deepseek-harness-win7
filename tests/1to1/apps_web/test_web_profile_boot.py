"""
Acceptance of the shipped Web entry: `dsh web` (`apps/web`'s dist is served by
`apps/cli`'s web entry — `reference/apps/web/package.json`).

Upstream composes this entry from the `@deepseek-ai/dsh-base` and
`@deepseek-ai/dsh-web-app` bundles
(`reference/packages/bundle/web-app/cordis.patch.yml`), which mount the
webserver, the client-connection transport, the client-module node half, the
frontend-static fallback owner and the browser roster.

This port's `build_harness(enable_web=True)` mounts that surface; the `web`
profile it is documented under has no preset file of its own, so the entry must
resolve the standard workspace preset rather than fail to read a preset that was
never shipped. These cases boot the entry and observe the served payload
through the real seat chain, so a Web GUI that cannot boot fails here.
"""

import os
import re

import pytest

from dsh.harness import build_harness
from dsh.host.webserver.webserver import HttpResponseWriter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class RecordingStream:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass


async def served_index(ctx):
    """Render the served document through the shipped fallback seat."""
    server = ctx.get("web_server")
    fallback = server._fallback
    assert fallback is not None, "the shipped composition claimed no frontend fallback"
    connection = ctx.get("connection")
    launch = connection.authenticated_url("http://127.0.0.1")
    token = launch.split("token=", 1)[1]
    exchange = HttpResponseWriter(RecordingStream())
    await fallback(
        {
            "method": "GET",
            "path": "/",
            "query": "token=" + token,
            "raw_url": "/?token=" + token,
            "headers": {"host": "127.0.0.1"},
            "body": b"",
        },
        exchange,
    )
    assert exchange.status == 303
    cookie = exchange.headers["set-cookie"].split(";", 1)[0]
    response = HttpResponseWriter(RecordingStream())
    await fallback(
        {
            "method": "GET",
            "path": "/",
            "query": "",
            "raw_url": "/",
            "headers": {"host": "127.0.0.1", "cookie": cookie},
            "body": b"",
        },
        response,
    )
    assert response.status == 200
    return bytes(response.body).decode("utf-8")


@pytest.mark.asyncio
async def test_web_profile_entry_boots_the_shipped_web_surface():
    ctx = await build_harness(mode="web", enable_web=True, verbose=False)
    # Every web surface row the app bundle mounts is present.
    assert ctx.get("web_server") is not None
    assert ctx.get("client_modules") is not None
    assert ctx.get("apiproxy") is not None
    assert ctx.get("connection") is not None
    server = ctx.get("web_server")
    assert server._fallback is not None

    body = await served_index(ctx)
    assert '<div id="root"></div>' in body
    assert 'globalThis["__DSH_BOOT__"]' in body
    graph = re.search(r'globalThis\["__DSH_BOOT__"\] = (\{.*?\})</script>', body, re.DOTALL)
    assert graph is not None, "the served index carries no boot graph"
    import json

    ids = [entry["id"] for entry in json.loads(graph.group(1))["entries"]]
    assert len(ids) > 30
    assert "@deepseek-ai/dsh-client-modules" in ids


@pytest.mark.asyncio
async def test_web_profile_entry_serves_the_built_dist_not_the_source_document():
    ctx = await build_harness(mode="web", enable_web=True, verbose=False)
    body = await served_index(ctx)
    assert "/src/" not in body
    assert re.search(r'<script type="module" crossorigin src="\./assets/[^"]+\.js"></script>', body) is not None
