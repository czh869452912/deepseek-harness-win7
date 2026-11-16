import asyncio

import pytest

from dsh.client.plugin_registry_probe import CurrentPluginRegistryProbe, REGISTRIES, fetch_ping
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.typert.remote import remote_methods
from scripts.rc022_registry_probe_probe import observe


@pytest.mark.asyncio
async def test_probe_race_shared_cache_and_cleanup_ownership():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 11
    assert all(row['withdrawn'] and row['rejected'] for row in rows.values())
    assert all(all(row['signals']) and not any(row['listeners']) for row in rows.values())
    assert rows['official']['value'] == REGISTRIES[0]
    assert rows['mirror']['value'] == REGISTRIES[1]
    assert rows['http-failure']['value'] == REGISTRIES[1]
    assert rows['cleanup-wait']['blocked'] is True
    assert rows['cleanup-reject']['value'] == REGISTRIES[1]
    assert rows['offline']['value'] is None and rows['offline']['cached'] is None
    assert rows['disabled']['calls'] == []
    assert rows['zero-ttl']['refreshed'] == REGISTRIES[1]
    assert rows['caller-cancel']['value'] == REGISTRIES[0]
    assert len([call for call in rows['official']['calls'] if 'endpoint' in call]) == 4
    ctx = Context()
    try:
        await ctx.plugin(CurrentPluginRegistryProbe)
        assert remote_methods(ctx.pluginRegistryProbe) == [dict(method='fastest', invocation=dict(kind='direct'))]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize('config', [dict(registryProbeTimeoutMs=0), dict(registryProbeTimeoutMs=2147483648), dict(registryProbeCacheTtlMs=-1)])
def test_probe_limits(config):
    assert CurrentPluginRegistryProbe.Config.validate(config).get('issues')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['ok', 'http-error', 'redirect', 'abort', 'cancel'])
async def test_real_http_headers_redirect_refusal_and_socket_cleanup(kind):
    entered = asyncio.Event()
    closed = asyncio.Event()
    handlers = []
    async def serve(reader, writer):
        handlers.append(asyncio.current_task())
        try:
            await reader.readuntil(b'\r\n\r\n')
            entered.set()
            if kind not in ('abort', 'cancel'):
                status = {'ok': '200 OK', 'http-error': '503 Unavailable', 'redirect': '302 Found'}[kind]
                writer.write(('HTTP/1.1 '+status+'\r\nLocation: /unexpected\r\nContent-Length: 100000\r\n\r\n').encode('ascii'))
                await writer.drain()
            assert await reader.read() == b''
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    controller = AbortController()
    task = asyncio.create_task(fetch_ping('http://127.0.0.1:%s/' % server.sockets[0].getsockname()[1], controller.signal, 5000))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if kind == 'abort':
            controller.abort()
            with pytest.raises(Exception):
                await asyncio.wait_for(task, 3)
        elif kind == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
        elif kind == 'redirect':
            with pytest.raises(Exception, match='redirect disallowed'):
                await task
        else:
            response = await task
            assert response.ok is (kind == 'ok')
            await response.body.cancel()
        await asyncio.wait_for(closed.wait(), 3)
        assert not controller.signal._listeners
    finally:
        controller.abort()
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers, return_exceptions=True)
