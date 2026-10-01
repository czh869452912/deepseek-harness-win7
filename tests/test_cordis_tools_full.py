"""Cordis tools exercise the real, shared, session-owned Host runner."""
import asyncio
import pytest
from types import SimpleNamespace
from canonical_web_fixture import web_context, close_web_context
from dsh.core.abort import NEVER_ABORTED
from dsh.typert.dispatch import RemoteDispatcher


@pytest.mark.asyncio
async def test_cordis_tools_mount_and_dispose_actual_plugin(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        runner = ctx.get('dynamicCordisRunner')
        await ctx.get('sessionController').create(dict(sessionId='cordis-tools', cwd=str(tmp_path), agentPreset='cordis'))
        agent = ctx.get('agents').get('cordis-tools')
        assert ctx.get('dynamicCordisRunner').typertRemote['service'] is runner.typertRemote['service']
        tools = ctx.get('tools')
        execution = SimpleNamespace(agent=agent, signal=NEVER_ABORTED)
        async def call(tool_name, **args):
            tool = next(t for t in tools.list_tools(scope=agent.ctx) if t.name == tool_name)
            return await tool.execute(args, execution)
        created = await call('cordis_define', plugin=dict(kind='new', idPrefix='theme'), name='Test', purpose='Prove actual activation', code=dict(host="def plugin(ctx):\n    ctx.provide('acceptanceTheme', 'dark')\n"))
        pid, package = created['pluginId'], created['packageId']
        assert ctx.get('acceptanceTheme') is None
        snapshot = await call('cordis_inspect_self')
        assert snapshot['plugins'][0]['pluginId'] == pid
        result = await call('cordis_run', pluginId=pid, packageId=package, mode='run')
        assert result['ok'], result
        assert ctx.get('acceptanceTheme') == 'dark'
        foreign = SimpleNamespace(id='different-session')
        assert runner.listPlugins(foreign) == []
        assert not (await runner.stop(foreign, pid))['ok']
        assert (await call('cordis_stop', pluginId=pid))['ok']
        assert ctx.get('acceptanceTheme') is None
        assert (await call('cordis_undefine', pluginId=pid))['ok']
        assert runner.listPlugins(agent) == []
        names = {t.name for t in tools.list_tools(scope=agent.ctx)}
        assert 'cordis_list_plugins' not in names
        assert 'cordis_run' in names
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_cordis_client_half_requires_browser_settlement(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='cordis-client', cwd=str(tmp_path), agentPreset='minimal'))
        agent = ctx.get('agents').get('cordis-client')
        runner = ctx.get('dynamicCordisRunner')
        created = runner.define(dict(sessionId=agent.id, plugin=dict(kind='new', idPrefix='panel'), name='Panel', purpose='Handshake', code=dict(client='return function(ctx) {}')))
        result = await runner.run(agent, created['pluginId'], created['packageId'], 'run')
        assert result['status'] == 'awaiting-approval'
        assert runner.inventory()[0]['latestRun']['status'] == 'awaiting-approval'
        assert 'currentPackageId' not in runner.inventory()[0]
        assert (await runner.stop(agent, created['pluginId']))['ok']
        assert not runner.pending
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_inspect_uses_real_scoped_tools_and_canonical_remote_settlement(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    pending = None
    try:
        for sid in ('inspect-owner', 'inspect-other'):
            await ctx.get('sessionController').create(dict(sessionId=sid, cwd=str(tmp_path), agentPreset='cordis'))
        agent = ctx.get('agents').get('inspect-owner')
        other = ctx.get('agents').get('inspect-other')
        registry = ctx.get('cordisInspect')
        tools = ctx.get('tools')
        execution = SimpleNamespace(agent=agent, signal=NEVER_ABORTED)
        async def call(name, **args):
            tool = next(tool for tool in tools.list_tools(scope=agent.ctx) if tool.name == name)
            return await tool.execute(args, execution)
        directory = await call('cordis_inspect_list')
        assert [row['id'] for row in directory['providers']] == ['Service', 'Event', 'Builtin', 'Tool']
        local_tools = agent.ctx.get('tools')
        dispose = local_tools.register_tool(dict(name='inspect_only_owner', description='Scoped probe',
            parameters=dict(type='object', properties={}), execute=lambda *_: dict(ok=True),
            output=dict(schema=dict(type='object'), render=lambda *_: [])))
        try:
            listing = await call('cordis_inspect_query', platform='host', provider='Tool', method='listTools')
            assert listing['data']['tools'] == tools.schemas(agent)
            assert 'inspect_only_owner' in {row['name'] for row in listing['data']['tools']}
            other_listing = await registry.query('host', 'Tool', 'listTools', {}, other, NEVER_ABORTED)
            assert 'inspect_only_owner' not in {row['name'] for row in other_listing['tools']}
        finally:
            dispose()
        gateway = RemoteDispatcher(ctx)
        async def remote(method, **args):
            return await gateway.invoke(dict(namespace='dynamicCordisRunner', method=method, args=args))
        client_manifest = dict(id='Slots', description='Client probe', methods=[dict(name='listSubTree', description='Read',
            inputSchema=dict(type='object', properties={}, additionalProperties=False),
            outputSchema=dict(type='object', properties=dict(root=dict(type='string')), required=['root'], additionalProperties=False))])
        assert await remote('syncInspectManifest', providers=[client_manifest]) is None
        received = asyncio.Queue()
        ctx.on('cordis/inspect-query', received.put_nowait)
        pending = asyncio.create_task(call('cordis_inspect_query', platform='client', provider='Slots', method='listSubTree'))
        request = await asyncio.wait_for(received.get(), 1)
        assert request == dict(requestId='inspect-1', agentId=agent.id, provider='Slots', method='listSubTree')
        fields = dict(requestId=request['requestId'], resolution=dict(ok=True, data=dict(root='workspace')))
        assert await remote('resolveInspectQuery', agentId=other.id, **fields) == dict(accepted=False)
        assert await remote('resolveInspectQuery', agentId=agent.id, requestId=request['requestId'], resolution=dict(ok=True, data=dict(root=1))) == dict(accepted=False)
        assert await remote('resolveInspectQuery', agentId=agent.id, **fields) == dict(accepted=True)
        assert await pending == dict(platform='client', provider='Slots', method='listSubTree', data=dict(root='workspace'))
        assert await remote('resolveInspectQuery', agentId=agent.id, **fields) == dict(accepted=False)
    finally:
        if pending is not None:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await close_web_context(ctx)
