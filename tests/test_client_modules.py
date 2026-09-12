"""
Tests for ClientModuleRegistry (`@deepseek-ai/dsh-client-modules`) and Web GUI Boot Architecture.
"""

import json
import os
import pytest
from dsh.cordis.context import Context
from dsh.host.client_modules.registry import (
    ClientModuleRegistry,
    ClientModulesPlugin,
    order_by_module_graph,
    short_hash,
)
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerPlugin, WebServerService


def test_short_hash():
    h = short_hash(b"hello deepseek win7")
    assert len(h) == 12
    assert isinstance(h, str)


def test_order_by_module_graph():
    entries = [
        {
            "id": "@deepseek-ai/dsh-client-ui-layout",
            "external": ["@deepseek-ai/dsh-client-ui-theme/client"],
            "rev": "111",
        },
        {
            "id": "@deepseek-ai/dsh-client-ui-theme",
            "external": [],
            "rev": "222",
        },
    ]
    ordered = order_by_module_graph(entries)
    ids = [e["id"] for e in ordered]
    assert ids.index("@deepseek-ai/dsh-client-ui-theme") < ids.index("@deepseek-ai/dsh-client-ui-layout")


@pytest.mark.asyncio
async def test_client_modules_plugin_and_route():
    ctx = Context()
    ctx.plugin(WebServerPlugin, config={"host": "127.0.0.1", "port": 9999})
    ctx.plugin(ClientModulesPlugin)

    registry: ClientModuleRegistry = ctx.get("client_modules")
    assert registry is not None

    # Register virtual bundle
    sample_bundle = b"window.__ModuleLoader__.load({ id: '@deepseek-ai/dsh-client-sample', factory: () => ({}) });"
    registry.register_virtual_bundle("@deepseek-ai/dsh-client-sample", sample_bundle)

    g = registry.graph()
    assert "rev" in g
    assert any(e["id"] == "@deepseek-ai/dsh-client-sample" for e in g["entries"])

    # Test HTTP handler for the generated combo resource the graph advertises
    server: WebServerService = ctx.get("web_server")
    route = server.match("/plugins/??@deepseek-ai/dsh-client-sample/client.js&rev=1")
    assert route is not None
    sample_row = [e for e in g["entries"] if e["id"] == "@deepseek-ai/dsh-client-sample"][0]

    class MockWriter:
        def __init__(self):
            self.data = bytearray()
            self.status = 0
            self.headers = {}
        def write(self, b): self.data.extend(b)
        async def drain(self): pass
        def write_status(self, s): self.status = s
        def write_header(self, k, v): self.headers[k] = v
        def write_body(self, b): self.data.extend(b)
        async def finish(self): pass

    writer = MockWriter()
    req = {
        "method": "GET",
        "path": sample_row["url"].split("&", 1)[0],
        "query": sample_row["url"].split("?", 1)[1],
        "raw_url": sample_row["url"],
        "headers": {},
        "body": b"",
    }
    resp = HttpResponseWriter(writer)
    await route.handler(req, resp)
    assert resp.status == 200
    assert resp.headers.get("content-type") == "text/javascript; charset=utf-8"
    assert resp.headers.get("cache-control") == "public, max-age=31536000, immutable"
    assert sample_bundle.rstrip(b"\n") in writer.data

    # An unknown resource (a stale revision, an unadvertised combination) is an
    # empty 404 rather than newer bytes.
    stale = dict(req, raw_url=sample_row["url"].replace(sample_row["rev"], "000000000000"))
    stale_resp = HttpResponseWriter(MockWriter())
    await route.handler(stale, stale_resp)
    assert stale_resp.status == 404

    # Test the boot rows against an explicit graph: the queue facade, one
    # preload row per application batch, one blocking script per bootstrap
    # batch, and the graph global last.
    graph = {
        "rev": "graph",
        "entries": [
            {"id": "@deepseek-ai/dsh-client-modules", "url": "/plugins/??a/client.js&rev=m", "rev": "m"},
            {"id": "@deepseek-ai/dsh-client-ui-renderer", "url": "/plugins/??b/client.js&rev=r", "rev": "r"},
        ],
        "batches": [
            {
                "phase": "bootstrap",
                "url": "/plugins/??a/client.js&rev=boot",
                "rev": "boot",
                "entries": ["@deepseek-ai/dsh-client-modules"],
            },
            {
                "phase": "application",
                "url": "/plugins/??b/client.js&rev=app",
                "rev": "app",
                "entries": ["@deepseek-ai/dsh-client-ui-renderer"],
            },
        ],
    }
    rows = registry.boot_injections(graph)
    assert rows[0]["kind"] == "script"
    assert "window.__ModuleLoader__={" in rows[0]["text"]
    assert "create(options){" in rows[0]["text"]
    assert rows[1] == {"kind": "script-preload", "src": graph["batches"][1]["url"]}
    assert rows[2] == {"kind": "script-src", "placement": "head", "src": graph["batches"][0]["url"]}
    assert rows[3] == {"kind": "global", "name": "__DSH_BOOT__", "value": graph}
