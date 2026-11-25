import asyncio
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from scripts import rc022_change_routes_probe as corpus


@pytest.mark.asyncio
async def test_authenticated_change_and_native_open_route_contracts(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'change-route-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    assert len(rows) == 56
    assert all(row['withdrawn'] and row['listeners'] == 0 for row in rows)
    by_name = {row['name']: row for row in rows}
    assert set(by_name['summary']['response']['body']) == {'turn', 'files', 'total', 'added', 'deleted'}
    assert by_name['summary']['calls'] == [dict(op='summary', sessionId='s', seq=7)]
    assert by_name['diff']['calls'] == [dict(op='diff', sessionId='s', seq=7, index=0)]
    assert by_name['applications']['calls'][-1] == dict(op='applications', request=dict(path='/host/current.txt'))
    assert by_name['application']['calls'][-1] == dict(op='open', request=dict(path='/host/current.txt', application='custom.app'))
    assert by_name['reveal']['calls'][-1] == dict(op='open', request=dict(path='/host/current.txt', action='reveal'))
    assert by_name['unmapped']['response']['status'] == 422
    assert by_name['open-unexpected']['response']['body'] == 'Changed file unavailable.'
    assert by_name['pending-disposal']['response'] == dict(error='This operation was aborted')
    for row in rows[-5:]:
        assert row['response']['status'] == 403 and row['calls'] == []


@pytest.mark.asyncio
async def test_actual_tcp_routes_authenticate_and_verify_viewed_cold_session_file(tmp_path):
    from dsh.client.ui_deliverables_022 import CurrentClientUiDeliverables022
    from dsh.host.connection.authorized import AuthorizedHostConnection, peer_bridge_handler
    from dsh.host.webserver.webserver import WebServerService
    from tests.test_present_open_current import fixture
    ctx, old_fiber, connection, calls, authenticated, directory, seq = await fixture(tmp_path, AuthorizedHostConnection)
    await old_fiber.dispose()
    summary = dict(turn=1, cwd=str(directory), files=[dict(path='output.docx', display='output.docx', added=1, deleted=0)],
                   total=1, added=1, deleted=0, snapshot=dict(before='private', after='private'))
    async def diff(*_):
        return dict(kind='binary', path='output.docx', display='output.docx')
    ctx.set_service('workspaceChanges', SimpleNamespace(summary=lambda sid, seq: summary, diff=diff))
    fiber = await ctx.plugin(CurrentClientUiDeliverables022)
    server = WebServerService(ctx, host='127.0.0.1', port=0)
    server.register('prefix', '/api', peer_bridge_handler(connection, connection.createSharedFetchHandler('/api')))
    await server.start()
    async def fetch(path, method='GET'):
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            writer.write((method+' '+path+' HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nContent-Length: 0\r\n\r\n').encode('ascii'))
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 5)
            headers, body = raw.split(b'\r\n\r\n', 1)
            return headers.lower(), body
        finally:
            writer.close()
            await writer.wait_closed()
    coordinates = '?'+urlencode(dict(sessionId='child', seq=seq, index=0, action='reveal'))
    try:
        authenticated[0] = False
        for route in ('summary', 'diff', 'open'):
            assert (await fetch('/api/changes.'+route+coordinates))[0].startswith(b'http/1.1 401')
        assert calls == []
        authenticated[0] = True
        headers, body = await fetch('/api/changes.summary'+coordinates)
        assert headers.startswith(b'http/1.1 200') and 'cwd' not in json.loads(body) and 'snapshot' not in json.loads(body)
        assert b'cache-control: no-store' in headers
        assert json.loads((await fetch('/api/changes.diff'+coordinates))[1])['kind'] == 'binary'
        assert (await fetch('/api/changes.open'+coordinates, 'POST'))[0].startswith(b'http/1.1 204')
        assert calls[-1][0] == dict(path=str((directory/'output.docx').resolve()), action='reveal')
        (directory/'output.docx').unlink()
        count = len(calls)
        assert (await fetch('/api/changes.open'+coordinates, 'POST'))[0].startswith(b'http/1.1 404') and len(calls) == count
        await fiber.dispose()
        assert (await fetch('/api/changes.summary'+coordinates))[0].startswith(b'http/1.1 404')
    finally:
        await server.stop()
        await ctx.fiber.dispose()
