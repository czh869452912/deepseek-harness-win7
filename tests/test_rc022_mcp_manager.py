import asyncio
import pytest
from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import AbortController
from scripts.rc022_candidate_fixture import setup
from scripts import rc022_mcp_server_probe_probe as peer
from dsh.typert.dispatch import RemoteDispatcher


async def wait(predicate):
    async def spin():
        while not predicate():await asyncio.sleep(.005)
    await asyncio.wait_for(spin(),5)


@pytest.mark.asyncio
async def test_real_loader_manager_watch_probe_volatile_disable_enable_and_remove(tmp_path):
    output=tmp_path/'peer';output.mkdir();peer.prepare(output);ctx=None;stream=None
    raw=dict(transport='streamable-http',url=peer.URL+'/fleet/legacy',enabled=False)
    try:
        ctx=await setup(tmp_path,extra=[('typert-registry',{}),('mcp-manager',dict(servers=dict(fleet=raw)))])
        manager=ctx.get('mcpManager');entry=next(item for item in ctx.loader.entries() if item.options['id']=='mcp-manager')
        await wait(lambda:manager.list()[0]['status']['state']=='disabled')
        fiber=entry.fiber
        controller=AbortController();stream=manager.watch(controller.signal)
        assert (await stream.__anext__())[0]['status']==dict(state='disabled')
        inspected=await RemoteDispatcher(ctx).invoke(dict(namespace='mcpManager',method='probe',args=dict(name='fleet')))
        assert inspected['ok'] and inspected['toolNames']==['a','b','c'] and inspected['closeConfirmed']
        assert manager.list()[0]['status']==dict(state='disabled')
        await await_callback_result(ctx.loader.update(entry.id,dict(config=dict(servers=dict(fleet=dict(raw,enabled=True))))))
        await wait(lambda:manager.list()[0]['status']['state']=='connected')
        assert entry.fiber is fiber and ctx.get('mcpManager')._instances is manager._instances
        assert any(row.name=='mcp__fleet__a' for row in ctx.tools.list_tools())
        first=manager._instances['fleet'].handle
        await manager.restart('fleet')
        await wait(lambda:manager.list()[0]['status']['state']=='connected')
        assert manager._instances['fleet'].handle is not first
        await await_callback_result(ctx.loader.update(entry.id,dict(config=dict(servers={}))))
        await wait(lambda:not manager.list())
        assert not any(row.name.startswith('mcp__fleet__') for row in ctx.tools.list_tools())
        controller.abort()
        with pytest.raises(StopAsyncIteration):await stream.__anext__()
        with pytest.raises(RuntimeError,match='unknown server'):await manager.restart('absent')
    finally:
        if stream is not None:await stream.aclose()
        if ctx is not None:await ctx.fiber.dispose()
        peer.stop_peer()


@pytest.mark.asyncio
async def test_manager_retains_unconfirmed_child_cleanup_after_entry_removal(tmp_path,monkeypatch):
    from tests.test_rc022_mcp_supervision import Peer
    transport=Peer(close_event=False);created=[]
    def create(_):created.append(transport);return transport
    monkeypatch.setattr('dsh.mcp.current.CurrentMcpConnection._create_transport',create)
    raw=dict(transport='stdio',command='controlled',closeTimeoutMs=20)
    ctx=await setup(tmp_path,extra=[('mcp-manager',dict(servers=dict(owned=raw)))])
    manager=ctx.get('mcpManager');record=None
    try:
        await wait(lambda:manager.list()[0]['status']['state']=='connected')
        record=manager._instances['owned'];wire=record.handle.plugin.connection.current.wire
        with pytest.raises(RuntimeError,match='cleanup.*incomplete'):await manager.restart('owned')
        assert len(created)==1 and manager.list()[0]['status']['reason']=='cleanup'
        entry=next(item for item in ctx.loader.entries() if item.options['id']=='mcp-manager')
        await await_callback_result(ctx.loader.update(entry.id,dict(config=dict(servers={}))))
        await wait(lambda:manager.list()[0]['configured'] is False)
        assert manager.list()[0]['status']['result']['closeConfirmed'] is False
        assert manager._instances['owned'] is record
        transport.on_close();await wait(lambda:wire._cleanup_work.done())
        assert manager.list()[0]['status']['result']['closeConfirmed'] is False
        assert not any(tool.name.startswith('mcp__owned__') for tool in ctx.tools.list_tools())
    finally:
        if record is not None:transport.on_close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_plugin_registration_lifetime_and_validation_before_mutating_config(tmp_path):
    output=tmp_path/'peer';output.mkdir();peer.prepare(output);ctx=None;contributor=None
    raw=dict(transport='streamable-http',url=peer.URL+'/contributed/modern')
    try:
        ctx=await setup(tmp_path,extra=[('mcp-manager',dict(servers={}))])
        manager=ctx.get('mcpManager');entry=next(item for item in ctx.loader.entries() if item.options['id']=='mcp-manager')
        def contribute(child):child.get('mcpManager').register('contributed',raw)
        contributor=await ctx.plugin(contribute)
        await wait(lambda:manager.list() and manager.list()[0]['status']['state']=='connected')
        with pytest.raises(RuntimeError,match='plugin already registers'):
            entry.fiber.resolveConfig(dict(servers=dict(contributed=raw)))
        # Loader contains rejected volatile writes; the live reference remains unchanged.
        await await_callback_result(ctx.loader.update(entry.id,dict(config=dict(servers=dict(contributed=raw)))))
        assert manager.config['servers'].get()=={}
        assert entry.fiber is not None and manager.list()[0]['configured']
        await contributor.dispose();contributor=None
        await wait(lambda:not manager.list())
        assert not any(row.name.startswith('mcp__contributed__') for row in ctx.tools.list_tools())
    finally:
        if contributor is not None:await contributor.dispose()
        if ctx is not None:await ctx.fiber.dispose()
        peer.stop_peer()
