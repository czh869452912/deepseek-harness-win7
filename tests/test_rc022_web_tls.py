import asyncio
from pathlib import Path
import socket
import threading

import pytest

from dsh.cordis import Context
from dsh.host.webserver import tls
from dsh.host.webserver.current import CONFIG, CurrentWebServer, CurrentWebServerPlugin
from scripts.rc022_web_tls_probe import observe, ROOT


@pytest.mark.asyncio
async def test_actual_tls_bind_and_transport_lifecycle():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 59
    assert rows['trusted-tls']['response'] == dict(status=200, body='SECURE')
    assert rows['trusted-tls']['origin'] == 'https://127.0.0.1:PORT'
    assert rows['untrusted-tls']['rejected'] and rows['plaintext-to-tls']['rejected']
    assert rows['parallel-handshake']['response']['status'] == 200
    assert rows['tls-upgrade']['status'] == 101
    assert rows['tls-unload']['closed'] == [True, True, True]
    assert rows['listener-retired']['rejected']
    assert rows['null-tls']['protocol'] == 'http:'


@pytest.mark.parametrize('config', [{}, dict(host='127.0.0.1'), dict(port=0), dict(host='127.0.0.1', port=-1),
    dict(host='127.0.0.1', port=65536), dict(host='127.0.0.1', port=0, tls={}),
    dict(host='127.0.0.1', port=0, tls=dict(certFile=3, keyFile='k'))])
def test_config_requires_concrete_host_port_and_complete_tls_pair(config):
    with pytest.raises(Exception): CONFIG(config)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['cert-missing', 'key-missing', 'cert-empty', 'key-empty', 'invalid', 'mismatch'])
async def test_tls_material_rejection_precedes_port_binding(tmp_path, failure):
    cert, key = (ROOT/'tests/fixtures/tls'/name for name in ('localhost-cert.pem', 'localhost-key.pem'))
    empty = tmp_path/'empty.pem'; empty.write_text(' \n\t', encoding='utf-8')
    invalid = tmp_path/'invalid.pem'; invalid.write_text('not PEM', encoding='utf-8')
    cfg = dict(certFile=str(cert), keyFile=str(key))
    if failure == 'cert-missing': cfg['certFile'] = str(tmp_path/'absent.pem')
    elif failure == 'key-missing': cfg['keyFile'] = str(tmp_path/'absent.pem')
    elif failure == 'cert-empty': cfg['certFile'] = str(empty)
    elif failure == 'key-empty': cfg['keyFile'] = str(empty)
    elif failure == 'invalid': cfg['certFile'] = str(invalid)
    else: cfg['keyFile'] = str(ROOT/'tests/fixtures/tls/proxy-test-key.pem')
    held = socket.socket(); held.bind(('127.0.0.1', 0)); held.listen()
    ctx = Context(); server = CurrentWebServer(ctx, port=held.getsockname()[1], tls=cfg)
    try:
        with pytest.raises(ValueError) as error: await server.start()
        assert 'webserver: ' in str(error.value)
        if failure.endswith('missing'): assert 'cannot read tls.' in str(error.value)
        elif failure.endswith('empty'): assert str(error.value).endswith(' is empty')
        else: assert 'are not a usable certificate and key pair:' in str(error.value)
        assert server._server is None and server.listened_port is None
    finally:
        await server.stop(); held.close(); await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disposal_waits_for_inflight_tls_file_read_and_closes_produced_listener(monkeypatch):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = tls.read_tls_file
    def gated(field, path):
        if field == 'certFile':
            entered.set(); assert release.wait(5)
            try: return original(field, path)
            finally: done.set()
        return original(field, path)
    monkeypatch.setattr(tls, 'read_tls_file', gated)
    ctx = Context()
    loading = asyncio.ensure_future(ctx.plugin(CurrentWebServerPlugin, dict(host='127.0.0.1', port=0, tls=dict(
        certFile=str(ROOT/'tests/fixtures/tls/localhost-cert.pem'), keyFile=str(ROOT/'tests/fixtures/tls/localhost-key.pem')))))
    disposal = None
    try:
        async def started():
            while not entered.is_set(): await asyncio.sleep(0)
        await asyncio.wait_for(started(), 2)
        server = ctx.webServer
        assert server.port is None
        disposal = asyncio.ensure_future(ctx.fiber.dispose())
        await asyncio.sleep(0)
        assert not disposal.done() and not done.is_set()
        release.set()
        await asyncio.wait_for(asyncio.gather(loading, disposal), 3)
        assert done.is_set() and server.port > 0 and server._server is None
    finally:
        release.set()
        await asyncio.gather(loading, *([disposal] if disposal else []), return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ipv6_loopback_binds_concrete_interface_and_reports_bracketed_origin():
    ctx = Context(); server = CurrentWebServer(ctx, host='::1', port=0)
    try:
        await server.start()
        assert server.getOrigin() == 'http://[::1]:' + str(server.port)
        reader, writer = await asyncio.open_connection('::1', server.port)
        try:
            writer.write(b'GET / HTTP/1.1\r\nHost: [::1]\r\n\r\n'); await writer.drain()
            assert (await asyncio.wait_for(reader.read(), 2)).startswith(b'HTTP/1.1 404')
        finally:
            writer.close(); await writer.wait_closed()
    finally:
        await server.stop(); await ctx.fiber.dispose()
