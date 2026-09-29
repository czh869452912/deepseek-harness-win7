import asyncio
import json

import pytest

from dsh.client.hmr import ClientHmrPlugin
from dsh.cordis.context import Context
from dsh.host.client_modules.registry import ClientModuleRegistry
from dsh.host.webserver.webserver import WebServerPlugin


async def frame(reader):
    while True:
        line = await asyncio.wait_for(reader.readline(), 3)
        if not line:
            raise AssertionError('SSE closed before expected frame')
        if line.startswith(b'data: '):
            return json.loads(line[6:])


@pytest.mark.asyncio
async def test_real_sse_rebuild_missing_file_recovery_and_unload(tmp_path):
    package = tmp_path / 'fixture'
    package.mkdir()
    (package / 'package.json').write_text(json.dumps({
        'name': '@fixture/client', 'exports': {'./client': './client.js'},
        'dsh': {'client': {'platform': 'web'}}}), encoding='utf-8')
    bundle = package / 'client.js'
    bundle.write_text('module.exports = 1;', encoding='utf-8')
    ctx = Context()
    registry = ClientModuleRegistry(ctx, search_dirs=[str(tmp_path)], roster={'@fixture/client'})
    ctx.set_service('clientModules', registry)
    await ctx.plugin(WebServerPlugin, config={'port': 0})
    plugin = await ctx.plugin(ClientHmrPlugin, config={'pollIntervalMs': 10})
    reader, writer = await asyncio.open_connection('127.0.0.1', ctx.get('webServer').port)
    writer.write(b'GET /plugins/events HTTP/1.1\r\nHost: localhost\r\n\r\n')
    await writer.drain()
    try:
        headers = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
        assert b'200 OK' in headers and b'text/event-stream' in headers
        initial = await frame(reader)
        assert initial == {'type': 'graph', 'graph': registry.graph()}
        bundle.write_text('module.exports = 200;', encoding='utf-8')
        rebuilt = await frame(reader)
        assert rebuilt == dict(type='rebuilt', id='@fixture/client', rev=registry.graph()['entries'][0]['rev'])
        assert rebuilt['rev'] != initial['graph']['entries'][0]['rev']
        bundle.unlink()
        await asyncio.sleep(.04)
        bundle.write_text('module.exports = 30000;', encoding='utf-8')
        recovered = await frame(reader)
        assert recovered['rev'] != rebuilt['rev']
        await asyncio.wait_for(plugin.dispose(), 3)
        await asyncio.wait_for(reader.read(), 3)
        assert not registry.rebuild_listeners and not registry._listeners
    finally:
        writer.close()
        await writer.wait_closed()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_route_registration_failure_releases_earlier_subscriptions():
    class Modules:
        def __init__(self):
            self.listeners = []
        def graph(self):
            return {'entries': []}
        def on_graph_changed(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)
        rebuild_listener = on_graph_changed
    class Server:
        def register(self, *args):
            raise RuntimeError('route rejected')
    ctx, modules = Context(), Modules()
    ctx.set_service('clientModules', modules)
    ctx.set_service('webServer', Server())
    try:
        with pytest.raises(Exception, match='route rejected'):
            await ctx.plugin(ClientHmrPlugin)
        assert not modules.listeners
    finally:
        await ctx.fiber.dispose()
