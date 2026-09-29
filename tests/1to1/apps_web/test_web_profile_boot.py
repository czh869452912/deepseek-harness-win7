"""Formal Web startup and teardown with all shipped business providers mounted."""
import asyncio
import pytest
from dsh.boot.profile_boot import run_profile


@pytest.mark.asyncio
@pytest.mark.parametrize('telemetry_disabled', [False, True])
async def test_formal_web_profile_starts_and_closes(tmp_path, monkeypatch, capsys, telemetry_disabled):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    monkeypatch.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    if telemetry_disabled:
        monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    else:
        monkeypatch.delenv('DSH_TELEMETRY_DISABLED', raising=False)
    result = await run_profile(dict(profile='web', dshHome=str(tmp_path),
        args=['--no-open', '--port', '0'], waitForExit=False))
    ctx = result['ctx']
    server = ctx.get('webServer')
    try:
        assert server._is_running
        for name in ('sessionController', 'workspaceController', 'sessionReferenceResolver', 'dynamicCordisRunner'):
            assert ctx.get(name) is not None
        assert (ctx.get('sessionTelemetry') is None) is telemetry_disabled
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        token = ctx.get('connection').browser_auth.launch_token
        writer.write(('GET /?token=%s HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' % token).encode('ascii'))
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        assert b'302' in response or b'303' in response
        cookie = next(line.split(b': ', 1)[1].split(b';', 1)[0] for line in response.split(b'\r\n') if line.lower().startswith(b'set-cookie:'))
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        writer.write(b'GET / HTTP/1.1\r\nHost: localhost\r\nCookie: ' + cookie + b'\r\nConnection: close\r\n\r\n')
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        assert b'200 OK' in response and b'__DSH_BOOT__' in response
    finally:
        result['shutdown'].shutdown(0)
        await result['shutdown'].wait()
    assert not server._is_running and not server._connections
    with pytest.raises(OSError):
        await asyncio.open_connection('127.0.0.1', server.port)
