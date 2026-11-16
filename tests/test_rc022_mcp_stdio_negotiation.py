import asyncio
import json
import sys
from pathlib import Path

import pytest

from scripts.rc022_candidate_fixture import setup
from scripts.rc022_mcp_stdio_negotiation_probe import observe
from scripts.rc022_mcp_result_probe import observe as result_observe
from scripts.oracles.rc022_mcp_negotiation_peer import alive
from dsh.mcp.stdio_current import CurrentStdioMcpTransport

PEER=Path(__file__).resolve().parents[1]/'scripts/oracles/rc022_mcp_negotiation_peer.py'


@pytest.mark.asyncio
async def test_actual_stdio_sibling_lifecycle_corpus(tmp_path,monkeypatch):
    monkeypatch.setattr('scripts.rc022_mcp_stdio_negotiation_probe.OUTPUT',tmp_path)
    rows=await observe()
    assert all(row['allClosed'] and not any(row['previousAlive']) for row in rows)
    assert [row['starts'] for row in rows]==[2,2,2,2,1]
    assert rows[-1]['value']['error']['code']=='ERA_NEGOTIATION_FAILED'
    (tmp_path/'stdio-negotiation-observations.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['legacy','modern'])
async def test_actual_loader_mcp_provider_uses_disposable_negotiation(tmp_path,mode):
    log=tmp_path/'peer.jsonl'
    ctx=await setup(tmp_path,extra=[('mcp-client',dict(transport='stdio',serverName='peer',command=sys.executable,
        args=[str(PEER),str(log),mode],reconnect=dict(enabled=False),failOnStartupError=True))])
    try:
        entry=next(entry for entry in ctx.loader.entries() if entry.options.get('id')=='mcp-client')
        connection=entry.fiber.plugin.connection
        assert isinstance(connection.client,CurrentStdioMcpTransport)
        assert connection.client.negotiated['era']==mode
        assert connection._connected_at is not None
        assert connection.instructions()=='### MCP server: peer\n\n'+mode.capitalize()+' literal {{model}}'
        process=connection.client.proc
    finally:await ctx.fiber.dispose()
    assert process.returncode is not None
    events=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    starts=[row for row in events if row['event']=='start']
    assert len(starts)==2 and not starts[1]['previousAlive']
    assert all(not alive(row['pid']) for row in starts)
    methods=[row['packet']['method'] for row in events if row['event']=='packet']
    assert ('initialize' in methods)==(mode=='legacy')
    assert ('notifications/initialized' in methods)==(mode=='legacy')
    (tmp_path/'stdio-provider-observations.json').write_text(json.dumps(dict(mode=mode,events=events,closed=True),indent=2),encoding='utf-8')


@pytest.mark.asyncio
async def test_connect_task_cancellation_reaps_disposable_process(tmp_path):
    log=tmp_path/'peer.jsonl';client=CurrentStdioMcpTransport(sys.executable,[str(PEER),str(log),'hold'])
    connecting=asyncio.create_task(client.connect())
    try:
        async def seen():
            while not log.exists() or 'server/discover' not in log.read_text(encoding='utf-8'):await asyncio.sleep(.005)
        await asyncio.wait_for(seen(),5);connecting.cancel()
        with pytest.raises(asyncio.CancelledError):await connecting
    finally:await client.close()
    starts=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if json.loads(line)['event']=='start']
    assert len(starts)==1 and all(not alive(row['pid']) for row in starts)
    assert client.proc is None


def test_modern_result_decode_and_dispatch_corpus():
    rows=asyncio.run(result_observe())
    assert len(rows)==100
    assert {row['decoded']['kind'] for row in rows}=={'complete','invalid','input_required'}


def test_default_request_rejects_input_required_with_sdk_guidance():
    from dsh.mcp.result_current import project_modern_result
    from dsh.mcp.negotiation_current import SdkError
    with pytest.raises(SdkError) as caught:
        project_modern_result('tools/call',dict(resultType='input_required',requestState='state'))
    assert caught.value.code=='UNSUPPORTED_RESULT_TYPE'
    assert caught.value.data==dict(resultType='input_required',method='tools/call')
    assert 'multi-round-trip auto-fulfilment is not enabled' in str(caught.value)
