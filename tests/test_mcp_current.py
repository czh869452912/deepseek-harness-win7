"""Cursor cycle rejection preserves callable generations through notification."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.mcp.current import CurrentMcpClient
from scripts.oracles.mcp_current_python import execute
from scripts.session_format_oracle import json_equal

CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/mcp_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_actual_source_mcp_cursor_contract(case):assert json_equal(execute(case),case['expected'])


def test_cycle_and_duplicate_failures_preserve_callable_registry_names():
    lookup={case['case']:case['expected'] for case in CASES}
    for name,count in [('repeated',2),('cycle',3),('space-cursor',2),('unicode-cursor',2)]:
        value=lookup[name]
        assert 'repeated a tools/list continuation cursor' in value['outcome']['error']
        assert value['names']==['mcp__test__old'] and not value['disposed'] and len(value['calls'])==count
    value=lookup['duplicate-before-next-fetch']
    assert 'listed tool "one" more than once' in value['outcome']['error'] and len(value['calls'])==1


@pytest.mark.asyncio
async def test_current_plugin_nonterminating_listing_preserves_then_successfully_replaces_generation(monkeypatch):
    class Peer:
        def __init__(self):self.on_close=None;self.on_notification=None;self.mode='first';self.requests=[];self.close_calls=0;self.server_capabilities=dict(tools={})
        async def start(self):pass
        async def connect(self):await self.start();return self
        async def request(self,value,**kwargs):
            self.requests.append(value)
            if value['method']=='tools/call':return dict(content=[dict(type='text',text='retained '+value['params']['name'])])
            if self.mode=='cycle':return dict(tools=[dict(name='changing'+str(len(self.requests)),inputSchema=dict(type='object'))],nextCursor='cycle')
            return dict(tools=[dict(name=self.mode,inputSchema=dict(type='object'))])
        async def close(self):
            self.close_calls+=1
            if self.on_close:self.on_close()
    peer=Peer();monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',lambda _:peer)
    ctx=Context();ctx.set_service('tools',ToolsService(ctx));plugin=CurrentMcpClient(dict(transport='stdio',serverName='current',command='fixture-peer',reconnect=dict(enabled=False)))
    try:
        fiber=await ctx.plugin(plugin)
        assert plugin.connection._opts['currentContract'] is True
        assert 'retained first' in await ctx.get('tools').execute_tool('mcp__current__first',{})
        peer.mode='cycle'
        await asyncio.wait_for(peer.on_notification(dict(method='notifications/tools/list_changed')),2)
        assert 'retained first' in await ctx.get('tools').execute_tool('mcp__current__first',{})
        calls=[call for call in peer.requests if call['method']=='tools/list']
        assert len(calls)==65 and all(call==dict(method='tools/list',params=dict(cursor='cycle')) for call in calls[2:])
        peer.mode='next'
        await peer.on_notification(dict(method='notifications/tools/list_changed'))
        assert not ctx.get('tools').has_tool('mcp__current__first')
        assert 'retained next' in await ctx.get('tools').execute_tool('mcp__current__next',{})
        await fiber.dispose()
        assert not ctx.get('tools').list_tools() and peer.close_calls==1
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_stdio_unchanged_repeated_cursor_converges_and_reaps_child(tmp_path):
    server=tmp_path/'repeating.py';record=tmp_path/'requests.jsonl'
    server.write_text('''import json,sys
from pathlib import Path
record=Path(sys.argv[1])
for line in sys.stdin:
 packet=json.loads(line)
 if 'id' not in packet:continue
 if packet.get('method')=='initialize':result=dict(protocolVersion='2025-11-25',capabilities=dict(tools={}),serverInfo=dict(name='repeat',version='1'))
 elif packet.get('method')=='tools/list':
  with record.open('a',encoding='utf-8') as stream:stream.write(json.dumps(packet)+'\\n')
  result=dict(tools=[],nextCursor='repeat')
 else:result={}
 print(json.dumps(dict(jsonrpc='2.0',id=packet['id'],result=result)),flush=True)
''',encoding='utf-8')
    ctx=Context();ctx.set_service('tools',ToolsService(ctx))
    plugin=CurrentMcpClient(dict(transport='stdio',serverName='real',command=sys.executable,args=[str(server),str(record)],reconnect=dict(enabled=False)))
    try:
        await asyncio.wait_for(ctx.plugin(plugin).await_settled(),5)
        outcome=await plugin.connection.ready
        assert outcome=={}
        assert not ctx.get('tools').list_tools()
        rows=[json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()]
        assert len(rows)==2 and rows[0].get('params',{})=={} and rows[1]['params']==dict(cursor='repeat')
        await ctx.fiber.dispose()
        assert plugin.connection.client is None and plugin.connection.disposed
    finally:await ctx.fiber.dispose()
