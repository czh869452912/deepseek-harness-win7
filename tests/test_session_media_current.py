"""Current file media contract and real bounded authenticated HTTP reads."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from dsh.api.session_media_current import CurrentSessionMediaReferences, serve_file
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.fs.fs_local import LocalFileSystem
from dsh.host.connection.current import CurrentHostConnection
from dsh.host.connection.http_current import current_bridge_handler
from dsh.host.webserver.webserver import WebServerService
from scripts.oracles.session_media_current_python import execute

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'scripts/oracles/session_media_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case'])
def test_actual_original_media_contribution(case):
    result = execute(case)
    assert result == case['expected'] and result['withdrawn']
    if case['case'].startswith('media-mime-'):
        assert result['response']['status'] == 200 and result['response']['hex'] == '000102ff'
        assert result['calls'][-1] == dict(method='read', sameTarget=True, signal=True, maxBytes=4)
    if case['case'] == 'media-head-bounded':
        assert result['response']['headers']['content-length'] == '4'
        assert [call['method'] for call in result['calls']] == ['resolve', 'stat']


@pytest.mark.asyncio
async def test_real_tcp_head_length_get_ranges_auth_and_route_unload(tmp_path):
    ctx = Context()
    server = WebServerService(ctx, host='127.0.0.1', port=0)
    authenticated = [True]
    calls = []
    try:
        await ctx.plugin(LocalFileSystem, config=dict(cwd=str(tmp_path)))
        ctx.set_service('attachments', SimpleNamespace(imageLimits=dict(maxImageBytes=4)))
        connection = CurrentHostConnection(ctx, [], SimpleNamespace(is_authenticated=lambda _: authenticated[0]))
        fiber = await ctx.plugin(CurrentSessionMediaReferences)
        server.register('prefix', '/api', current_bridge_handler(connection, connection.createSharedFetchHandler('/api')))
        await server.start()
        target = tmp_path / 'payload.html'
        target.write_bytes(b'<p/>')
        fs = ctx.get('fs')
        resolve = fs.resolve
        async def recorded(*args):
            calls.append(args)
            return await resolve(*args)
        fs.resolve = recorded
        async def fetch(method, path=str(target), extra=''):
            reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
            try:
                writer.write((method + ' /api/file?' + urlencode(dict(path=path)) +
                              ' HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n' + extra + '\r\n').encode('ascii'))
                await writer.drain()
                raw = await asyncio.wait_for(reader.read(), 5)
                headers, body = raw.split(b'\r\n\r\n', 1)
                return headers.lower(), body
            finally:
                writer.close()
                await writer.wait_closed()
        head, body = await fetch('HEAD')
        assert head.startswith(b'http/1.1 200') and b'content-length: 4\r\n' in head + b'\r\n' and body == b''
        assert head.count(b'content-length:') == 1
        get, body = await fetch('GET', extra='Range: bytes=0-0\r\n')
        assert get.startswith(b'http/1.1 200') and body == b'<p/>'
        assert b'content-security-policy: sandbox' in get and b'content-type: text/html' in get
        assert get.count(b'content-length:') == 1
        target.write_bytes(b'12345')
        assert (await fetch('GET'))[0].startswith(b'http/1.1 413')
        assert (await fetch('HEAD'))[1] == b''
        count = len(calls)
        authenticated[0] = False
        assert (await fetch('GET'))[0].startswith(b'http/1.1 401')
        assert len(calls) == count
        authenticated[0] = True
        assert (await fetch('HEAD', path=str(tmp_path / 'missing')))[0].startswith(b'http/1.1 404')
        await fiber.dispose()
        assert (await fetch('GET'))[0].startswith(b'http/1.1 404')
    finally:
        await server.stop()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_fs_post_stat_growth_and_preaborted_provider(tmp_path):
    ctx = Context()
    try:
        await ctx.plugin(LocalFileSystem, config=dict(cwd=str(tmp_path)))
        fs = ctx.get('fs')
        path = tmp_path / 'grow.mp4'
        path.write_bytes(b'1234')
        def grow(*_args):
            with path.open('ab') as stream:
                stream.write(b'5')
        fs.internals.inspectReadBytesAfterStat = grow
        request = dict(method='GET', url='http://host/api/file?' + urlencode(dict(path=str(path))), signal=AbortController().signal)
        result = await serve_file(request, fs, 4)
        assert result['status'] == 413 and result['body'] == 'FS_TOO_LARGE'
        controller = AbortController()
        controller.abort(RuntimeError('gone'))
        request['signal'] = controller.signal
        result = await serve_file(request, fs, 4)
        assert result['status'] == 499 and result['body'] == 'FS_ABORTED'
    finally:
        await ctx.fiber.dispose()
