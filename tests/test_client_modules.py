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

    # Test HTTP handler for bundle
    server: WebServerService = ctx.get("web_server")
    route = server.match("/plugins/@deepseek-ai/dsh-client-sample/client.js")
    assert route is not None

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
        "path": "/plugins/@deepseek-ai/dsh-client-sample/client.js",
        "query": "",
        "headers": {},
        "body": b"",
    }
    resp = HttpResponseWriter(writer)
    await route.handler(req, resp)
    assert resp.status == 200
    assert resp.headers.get("Content-Type") == "application/javascript; charset=utf-8"
    assert sample_bundle in writer.data

    # Test index tap injection
    html_in = "<html><head><title>Test</title></head><body></body></html>"
    tapped = registry.tap_index(html_in)
    assert "window.__DSH_BOOT__" in tapped
    assert "create(options)" in tapped
    assert "window.__ModuleLoader__" in tapped
