import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.mcp import server_probe_current as module
from dsh.mcp.deadline_current import with_deadline
from scripts import rc022_mcp_server_probe_probe as corpus
from scripts.oracles.rc022_mcp_negotiation_peer import alive


@pytest.mark.asyncio
async def test_real_http_probe_and_sdk_pagination_corpus(tmp_path):
    corpus.prepare(tmp_path)
    try:
        rows = await corpus.observe()
        assert len(rows) == 50
        assert rows[0]['result']['toolNames'] == ['a','b','c']
        assert rows[2]['result']['truncated'] is True
        assert rows[8]['result']['toolNames'] == []
        assert rows[38]['result']['stage'] == 'connect'
        assert rows[40]['result']['message'] == 'Error: MCP operation timed out'
        assert rows[41]['result']['message'] == 'probe aborted'
        assert rows[46]['result']['listing']['tools'] == [dict(name=name,inputSchema=dict(type='object')) for name in ('a','b','c')]
        (tmp_path/'probe-observations.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    finally:corpus.stop_peer()


@pytest.mark.asyncio
async def test_probe_task_cancellation_closes_and_settles_owned_actual_io(tmp_path,monkeypatch):
    instances=[]
    class Captured(module.McpGeneration):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);instances.append(self)
    monkeypatch.setattr(module,'McpGeneration',Captured)
    corpus.prepare(tmp_path);ctx=Context()
    try:
        task=asyncio.create_task(module.probe_server(ctx,dict(transport='streamable-http',url=corpus.URL+'/cancel/hold',serverName='cancel',closeTimeoutMs=500)))
        async def entered():
            while not corpus.LOG.exists() or not any(row['packet']['method']=='tools/list' for row in corpus.records()):await asyncio.sleep(.005)
        await asyncio.wait_for(entered(),5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        generation=instances[0]
        assert await generation.close() == dict(closeConfirmed=True)
        assert generation._cleanup_work.done() and not generation._pending
        assert generation.client.transport is None
        assert not generation.transport._writers and not generation.transport._tasks
    finally:
        await ctx.fiber.dispose();corpus.stop_peer()


@pytest.mark.asyncio
async def test_preaborted_probe_never_constructs_transport(monkeypatch):
    def forbidden(_):raise AssertionError('transport constructed after pre-abort')
    monkeypatch.setattr('dsh.mcp.generation_current.create_current_transport',forbidden)
    controller=AbortController();controller.abort();ctx=Context()
    try:
        result=await module.probe_server(ctx,dict(serverName='aborted',transport='streamable-http',url='http://127.0.0.1:9'),dict(signal=controller.signal))
        assert result['ok'] is False and result['message']=='probe aborted' and result['closeConfirmed'] is True
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['legacy','modern'])
async def test_stdio_probe_uses_own_identity_and_reaps_probe_and_serving_processes(tmp_path,mode):
    peer=Path(__file__).resolve().parents[1]/'scripts/oracles/rc022_mcp_negotiation_peer.py'
    log=tmp_path/'peer.jsonl';ctx=Context()
    try:
        result=await module.probe_server(ctx,dict(transport='stdio',command=sys.executable,args=[str(peer),str(log),mode],serverName='stdio',closeTimeoutMs=2000))
        assert result['ok'] is True and result['closeConfirmed'] is True and result['toolNames']==[]
        events=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        starts=[row for row in events if row['event']=='start']
        assert len(starts)==2 and all(not row['previousAlive'] and not alive(row['pid']) for row in starts)
        packets=[row['packet'] for row in events if row['event']=='packet']
        discovery=next(packet for packet in packets if packet['method']=='server/discover')
        assert discovery['params']['_meta']['io.modelcontextprotocol/clientInfo']['name']=='dsh-mcp-probe'
        if mode=='legacy':
            assert next(packet for packet in packets if packet['method']=='initialize')['params']['clientInfo']['name']=='dsh-mcp-probe'
        else:
            assert next(packet for packet in packets if packet['method']=='tools/list')['params']['_meta']['io.modelcontextprotocol/clientInfo']['name']=='dsh-mcp-probe'
        (tmp_path/'stdio-probe-observations.json').write_text(json.dumps(dict(result=result,events=events),indent=2),encoding='utf-8')
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_node_timer_overflow_bounds_caller_without_cancelling_actual_work():
    held=asyncio.get_running_loop().create_future();started=time.perf_counter()
    with pytest.raises(RuntimeError,match='overflow deadline'):
        await with_deadline(held,9007199254740992,'overflow deadline')
    assert time.perf_counter()-started < .5 and not held.cancelled()
    held.set_result('released');await asyncio.sleep(0)
