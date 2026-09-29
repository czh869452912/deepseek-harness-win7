import asyncio
import socket

import pytest

from dsh.boot.profile_boot import create_app_ready
from dsh.bundle.web_app.runtime import WebRuntimePlugin
from dsh.bundle.web_app import runtime, trust
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.host.connection.canonical import CanonicalConnectionPlugin
from dsh.host.webserver.webserver import WebServerPlugin


async def request(port, path='/', headers=None):
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    fields = dict(host='127.0.0.1:%s' % port, **(headers or {}))
    writer.write(('GET %s HTTP/1.1\r\n' % path + ''.join('%s: %s\r\n' % item for item in fields.items()) + '\r\n').encode())
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), 3)
    writer.close()
    await writer.wait_closed()
    return raw


@pytest.mark.asyncio
async def test_bound_runtime_auth_and_ready_owned_announcement(tmp_path, capsys):
    ctx = Context()
    ready = create_app_ready()
    ctx.set_service('appReady', ready['service'])
    await ctx.plugin(CredentialsLocalPlugin, config={'path': str(tmp_path / 'credentials.yaml'), 'watch': False})
    await ctx.plugin(WebServerPlugin, config={'port': 0})
    server = ctx.get('webServer')
    assert server.port > 0 and server._is_running
    await ctx.plugin(WebRuntimePlugin, config={'openBrowser': False, 'surfaceContext': False})
    await ctx.plugin(CanonicalConnectionPlugin)
    try:
        await asyncio.sleep(0)
        assert 'dsh web:' not in capsys.readouterr().out
        ready['commit']()
        await asyncio.sleep(0)
        output = capsys.readouterr().out
        assert 'dsh web: http://127.0.0.1:%s/?token=' % server.port in output
        assert ctx.get('webRuntime') == {'lanAddresses': [], 'trustedHosts': []}
        assert (await request(server.port)).startswith(b'HTTP/1.1 401')
        token = ctx.get('connection').authenticated_url('http://127.0.0.1:%s' % server.port).split('?', 1)[1]
        exchange = await request(server.port, '/?' + token)
        assert exchange.startswith(b'HTTP/1.1 303')
        cookie = next(line.split(b': ', 1)[1].split(b';', 1)[0] for line in exchange.split(b'\r\n') if line.lower().startswith(b'set-cookie:')).decode()
        served = await request(server.port, headers={'cookie': cookie})
        assert served.startswith(b'HTTP/1.1 200') and b'<html' in served
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        writer.write(b'GET / HTTP/1.1\r\n')  # Incomplete headers must not survive owner disposal.
        await writer.drain()
        await asyncio.sleep(.01)
        await ctx.fiber.dispose()
        assert not server._is_running and not server._connections
        assert await asyncio.wait_for(reader.read(), 2) == b''
        writer.close()
        await writer.wait_closed()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_bind_never_publishes_server_service():
    occupied = socket.socket()
    occupied.bind(('127.0.0.1', 0))
    occupied.listen()
    ctx = Context()
    try:
        with pytest.raises(Exception):
            await ctx.plugin(WebServerPlugin, config={'port': occupied.getsockname()[1]})
        assert ctx.get('webServer') is None
    finally:
        occupied.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ssh_suppresses_browser_and_unload_before_ready_suppresses_url(tmp_path, monkeypatch, capsys):
    opened = []
    async def open_browser(url):
        opened.append(url)
    monkeypatch.setattr(runtime, 'open_browser', open_browser)
    for early in (True, False):
        ctx = Context()
        ready = create_app_ready()
        ctx.set_service('appReady', ready['service'])
        ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([{'source': 'process', 'values': {'SSH_TTY': 'fixture'}}]))
        await ctx.plugin(CredentialsLocalPlugin, config={'path': str(tmp_path / 'credentials.yaml'), 'watch': False})
        await ctx.plugin(WebServerPlugin, config={'port': 0})
        await ctx.plugin(WebRuntimePlugin, config={'surfaceContext': False})
        await ctx.plugin(CanonicalConnectionPlugin)
        if early:
            await ctx.fiber.dispose()
        ready['commit']()
        await asyncio.sleep(0)
        assert ('dsh web:' in capsys.readouterr().out) is (not early)
        assert not opened
        await ctx.fiber.dispose()


def test_lan_snapshot_preserves_interface_order_and_explicit_duplicates(monkeypatch):
    calls = []
    def addresses():
        calls.append(True)
        return ['10.0.0.2', '192.168.1.2']
    monkeypatch.setattr(trust, 'ipv4_interfaces', addresses)
    assert trust.resolve_lan_trust('127.0.0.1', ['internal:3080']) == dict(lanAddresses=[], trustedHosts=['internal:3080'])
    assert not calls
    assert trust.resolve_lan_trust('0.0.0.0', ['10.0.0.2']) == dict(
        lanAddresses=['10.0.0.2', '192.168.1.2'], trustedHosts=['10.0.0.2', '192.168.1.2', '10.0.0.2'])
    assert calls == [True]
