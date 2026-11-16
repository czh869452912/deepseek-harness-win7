import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from dsh.core.abort import NEVER_ABORTED
from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport,encode_mcp_param_value
from scripts import rc022_mcp_http_negotiation_probe as fixture
from scripts.rc022_candidate_fixture import setup


@pytest.mark.asyncio
async def test_actual_http_probe_and_business_header_corpus(tmp_path):
    fixture.prepare(tmp_path)
    try:
        rows=await fixture.observe()
        assert len(rows)==13
        assert {row['value']['error']['code'] for row in rows if 'error' in row['value']}=={'CLIENT_HTTP_AUTHENTICATION','CLIENT_HTTP_FORBIDDEN','ERA_NEGOTIATION_FAILED','REQUEST_TIMEOUT'}
        modern=next(row for row in rows if row['mode']=='modern')
        assert modern['value']['sessionId'] is None
        assert not any(row['packet']['method']=='initialize' for row in modern['requests'])
        read=modern['requests'][-1]
        assert read['headers']['mcp-name']==encode_mcp_param_value('doc://\u6587\u6863/one')
        legacy=next(row for row in rows if row['mode']=='legacy')
        assert legacy['value']['sessionId']=='fixture-session'
        assert 'mcp-session-id' not in next(row for row in legacy['requests'] if row['packet']['method']=='initialize')['headers']
        (tmp_path/'http-negotiation-observations.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    finally:fixture.stop_peer()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['legacy','modern'])
async def test_actual_loader_http_mcp_resources_and_unload(tmp_path,mode):
    fixture.prepare(tmp_path)
    ctx=None
    try:
        config=dict(transport='streamable-http',serverName='web',url=fixture.URL+'/loader/'+mode,headers=fixture.HEADERS,reconnect=dict(enabled=False),failOnStartupError=True)
        ctx=await setup(tmp_path,extra=[('mcp-resources',{}),('mcp-client',config)])
        entry=next(entry for entry in ctx.loader.entries() if entry.options.get('id')=='mcp-client')
        connection=entry.fiber.plugin.connection;client=connection.client
        assert isinstance(client,CurrentStreamableHttpMcpTransport) and connection._connected_at is not None
        result=await ctx.mcpResources._request('web',dict(method='resources/read',uri='doc://\u6587\u6863/one'),NS(signal=NEVER_ABORTED,agent=None))
        assert result['contents'][0]['blob']=='YWJj'
        assert connection.instructions()=='### MCP server: web\n\n'+mode.capitalize()+' literal {{model}}'
        await ctx.fiber.dispose();ctx=None
        assert client._closed and not client._pending and not client._writers and not client._tasks
        assert not client._probe_channel._probe_send_tasks
        (tmp_path/'http-provider-observations.json').write_text(json.dumps(dict(mode=mode,result=result,events=fixture.records(),closed=True),indent=2),encoding='utf-8')
    finally:
        if ctx is not None:await ctx.fiber.dispose()
        fixture.stop_peer()


@pytest.mark.asyncio
async def test_http_connect_task_cancellation_drains_probe_send_and_writers(tmp_path):
    fixture.prepare(tmp_path)
    client=CurrentStreamableHttpMcpTransport(fixture.URL+'/native/hold')
    connecting=asyncio.create_task(client.connect())
    try:
        async def seen():
            while not fixture.LOG.exists() or not any((row.get('packet') or {}).get('method')=='server/discover' for row in fixture.records()):await asyncio.sleep(.005)
        await asyncio.wait_for(seen(),5);connecting.cancel()
        with pytest.raises(asyncio.CancelledError):await connecting
        assert client._closed and not client._writers and not client._tasks and not client._probe_channel._probe_send_tasks
    finally:
        await client.close();fixture.stop_peer()


def test_mcp_name_header_encoding_handles_sentinel_and_utf16():
    assert encode_mcp_param_value('plain\tvalue')=='plain\tvalue'
    assert encode_mcp_param_value(' space ')=='=?base64?IHNwYWNlIA==?='
    assert encode_mcp_param_value('=?base64?text?=')!='=?base64?text?='
    assert encode_mcp_param_value('\ud800')=='=?base64?77+9?='
