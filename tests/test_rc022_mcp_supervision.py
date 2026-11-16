import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolsService
from dsh.mcp.current import CurrentMcpClient
from dsh.mcp.status_current import connection_status_in
from scripts import rc022_mcp_supervision_probe as corpus


async def wait(predicate):
    async def spin():
        while not predicate():await asyncio.sleep(.005)
    await asyncio.wait_for(spin(),3)


def config(**changes):
    return dict(dict(transport='stdio',serverName='owned',command='controlled',reconnect=dict(enabled=False),closeTimeoutMs=500),**changes)


class Peer:
    def __init__(self, name='first', close_event=True):
        self.name,self.close_event=name,close_event
        self.on_close=self.on_notification=None
        self.server_capabilities=dict(tools={},resources={})
        self.server_instructions='literal {{model}}'
        self.close_calls=0
        self.started=self.closed=False
        self.list_entered=asyncio.Event()
        self.held=None
        self.failure=None

    async def start(self):self.started=True
    async def connect(self):await self.start();return self
    async def request(self, packet, **options):
        if packet['method']=='tools/list':
            self.list_entered.set()
            if self.held is not None:return await asyncio.shield(self.held)
            return dict(tools=[dict(name=self.name,inputSchema=dict(type='object'))])
        if self.failure is not None:raise RuntimeError(self.failure)
        return dict(content=[dict(type='text',text='ok')])
    async def close(self):
        self.close_calls+=1;self.closed=True
        if self.close_event and self.on_close is not None:self.on_close()


def registry():
    ctx=Context();ctx.set_service('tools',ToolsService(ctx));return ctx


@pytest.mark.asyncio
async def test_real_source_supervisor_http_corpus(tmp_path):
    corpus.prepare(tmp_path)
    try:
        rows=await corpus.observe()
        assert len(rows)==30
        credentials=next(row for row in rows if row.get('mode')=='credentials')
        assert [row['status']['state'] for row in credentials['checkpoints']]==['waiting-credentials','connected','connected','waiting-credentials','closed']
        assert next(row for row in rows if row.get('mode')=='reconnect-budget')['checkpoints'][-2]['status']['reason']=='gave-up'
        cleanup=next(row for row in rows if row.get('mode')=='tool-cleanup-error')
        assert '[redacted]' in cleanup['checkpoints'][-1]['closure']['cleanupError']
        assert all('synthetic/token' not in row['message'] for row in cleanup['logs'])
        (tmp_path/'supervisor-observations.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    finally:corpus.peer.stop_peer()


@pytest.mark.asyncio
async def test_status_cell_survives_real_fiber_reload_and_detaches_on_final_disposal(monkeypatch):
    peers=[]
    def create(_):peer=Peer(str(len(peers)));peers.append(peer);return peer
    monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',create)
    ctx=registry();plugin=CurrentMcpClient(config())
    try:
        fiber=await ctx.plugin(plugin);cell=connection_status_in(fiber);trace=[];cell.onChange(lambda row:trace.append(row))
        assert cell.current()['state']=='connected' and cell.closure()==dict(closeConfirmed=False)
        await await_callback_result(fiber.update(config(toolCallTimeoutMs=123)))
        await fiber.await_settled()
        assert connection_status_in(fiber) is cell and len(peers)==2 and peers[0].closed
        assert [row['state'] for row in trace]==['closed','connecting','connected']
        assert ctx.tools.has_tool('mcp__owned__1') and not ctx.tools.has_tool('mcp__owned__0')
        await fiber.dispose()
        assert cell.current()==dict(state='closed',result=dict(closeConfirmed=True))
        count=len(trace);cell.update(dict(state='connecting',attempt=99));assert len(trace)==count
        assert all(peer.close_calls==1 for peer in peers)
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_late_startup_listing_is_not_published_after_budget_expires(monkeypatch):
    peer=Peer();peer.held=asyncio.get_running_loop().create_future()
    monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',lambda _:peer)
    ctx=registry();plugin=CurrentMcpClient(config(startupTimeoutMs=20));fiber=ctx.plugin(plugin)
    try:
        await peer.list_entered.wait();await wait(lambda:peer.closed)
        assert not ctx.tools.list_tools()
        peer.held.set_result(dict(tools=[dict(name='late',inputSchema=dict(type='object'))]))
        await fiber.await_settled()
        assert 'startup timed out' in str(plugin.connection.ready.result()['error'])
        assert not ctx.tools.list_tools() and plugin.status.current()['reason']=='reconnect-disabled'
        assert plugin.status.closure()==dict(closeConfirmed=True)
    finally:
        if not peer.held.done():peer.held.set_result(dict(tools=[]))
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_reconnect_waits_for_actual_resync_and_ignores_its_late_definition(monkeypatch):
    peers=[]
    def create(_):peer=Peer('old' if not peers else 'new');peers.append(peer);return peer
    monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',create)
    ctx=registry();plugin=CurrentMcpClient(config(reconnect=dict(enabled=True,initialDelayMs=2,maxDelayMs=10000,maxAttempts=1)));refresh=None
    try:
        await ctx.plugin(plugin);first=peers[0]
        first.held=asyncio.get_running_loop().create_future();first.list_entered.clear()
        refresh=asyncio.create_task(first.on_notification(dict(method='notifications/tools/list_changed')))
        await first.list_entered.wait();await first.close();await asyncio.sleep(.025)
        assert len(peers)==1 and ctx.tools.has_tool('mcp__owned__old')
        first.held.set_result(dict(tools=[dict(name='late',inputSchema=dict(type='object'))]))
        await refresh;await wait(lambda:len(peers)==2 and plugin.status.current()['state']=='connected')
        assert ctx.tools.has_tool('mcp__owned__new') and not ctx.tools.has_tool('mcp__owned__late')
        assert not ctx.tools.has_tool('mcp__owned__old')
    finally:
        if peers and peers[0].held is not None and not peers[0].held.done():peers[0].held.set_result(dict(tools=[]))
        if refresh is not None:await asyncio.gather(refresh,return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unconfirmed_close_blocks_reconnect_and_same_fiber_replacement(monkeypatch):
    peer=Peer(close_event=False);calls=[]
    def create(_):calls.append(1);return peer
    monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',create)
    ctx=registry();plugin=CurrentMcpClient(config(closeTimeoutMs=20));record=None
    try:
        fiber=await ctx.plugin(plugin);record=plugin.connection.current
        await peer.close();plugin.connection._lost(record,'controlled loss')
        await wait(lambda:plugin.status.current().get('reason')=='unclosed-generation')
        assert len(calls)==1 and plugin.status.closure()['closeConfirmed'] is False
        cell=plugin.status
        with pytest.raises(RuntimeError,match='previous connection cleanup is incomplete'):
            await await_callback_result(fiber.update(config(closeTimeoutMs=20)))
            await fiber.await_settled()
        assert connection_status_in(fiber) is cell and len(calls)==1
        # Release the deliberately suppressed close event after preserving the failure.
        peer.on_close();await wait(lambda:record.wire._cleanup_work.done())
        assert not cell.closure()['closeConfirmed']
    finally:
        if record is not None and not record.wire._closed.is_set():peer.on_close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_credential_enabled_tool_and_resource_failures_redact_resolved_history(monkeypatch):
    peer=Peer();monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',lambda _:peer)
    ctx=registry();ctx.set_service('credentials',SimpleNamespace(resolve=lambda _:dict(value='synthetic/token')))
    plugin=CurrentMcpClient(config(expandTemplates=True,env=dict(TOKEN='${credential:TOKEN}')))
    try:
        await ctx.plugin(plugin);peer.failure='failed synthetic/token synthetic%2Ftoken'
        tool=await ctx.tools.execute_tool('mcp__owned__first',{})
        assert 'synthetic' not in tool and '[redacted]' in tool
        with pytest.raises(RuntimeError) as failure:
            await plugin.connection.request_resource(dict(method='resources/read',uri='doc://private'),SimpleNamespace(signal=NEVER_ABORTED))
        assert 'synthetic' not in str(failure.value) and '[redacted]' in str(failure.value)
    finally:await ctx.fiber.dispose()
