"""Cordis tools exercise the real, shared, session-owned Host runner."""
import asyncio
import pytest
from types import SimpleNamespace
from canonical_web_fixture import web_context, close_web_context
from dsh.core.abort import NEVER_ABORTED
from dsh.llm.message import create_user_message
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
        assert result['status'] == 'running', result
        assert result['host'] == dict(status='running', provides=['acceptanceTheme'], waitingFor=[])
        assert result['client'] == dict(status='absent', waitingFor=[])
        assert ctx.get('acceptanceTheme') == 'dark'
        foreign = SimpleNamespace(id='different-session')
        assert runner.listPlugins(foreign) == []
        assert not (await runner.stop(foreign, pid))['ok']
        assert await call('cordis_stop', pluginId=pid) == dict(pluginId=pid)
        assert ctx.get('acceptanceTheme') is None
        assert await call('cordis_undefine', pluginId=pid) == dict(pluginId=pid, wasRunning=False)
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
async def test_cordis_reference_version_and_diagnostics_through_canonical_web(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        for sid in ('cordis-owner', 'cordis-foreign'):
            await ctx.get('sessionController').create(dict(sessionId=sid, cwd=str(tmp_path), agentPreset='cordis'))
        agent = ctx.get('agents').get('cordis-owner')
        foreign = ctx.get('agents').get('cordis-foreign')
        runner = ctx.get('dynamicCordisRunner')
        tools = ctx.get('tools')
        execution = SimpleNamespace(agent=agent, signal=NEVER_ABORTED)
        def tool(name):
            return next(item for item in tools.list_tools(scope=agent.ctx) if item.name == name)
        async def call(tool_name, **args):
            return await tool(tool_name).execute(args, execution)
        source = "def plugin(ctx):\n    ctx.provide('referenceProbe', 'first')\n    harness.handle('read', lambda args: {'value': ctx.get('referenceProbe')})\n"
        first = await call('cordis_define', plugin=dict(kind='new', idPrefix='theme'), name='First', purpose='Reference journey', code=dict(host=source))
        assert first['pluginId'] == 'theme-1'
        assert first['packageId'] == 'pkg-1'
        assert tool('cordis_define').present_call(dict(plugin=dict(kind='new', idPrefix='theme'), name='First', purpose='Reference journey', code=dict(host=source)))['rawInput'] == dict(host=source)
        pid = first['pluginId']
        await call('cordis_run', pluginId=pid, packageId=first['packageId'], mode='run')
        current = await call('cordis_inspect_self', pluginId=pid, packageId=first['packageId'])
        assert current['runtime']['host'] == dict(status='running', provides=['referenceProbe'], waitingFor=[], handlers=['read'])
        assert current['code'] == dict(host=source)
        assert current['plugin']['state'] == 'running'
        assert 'packages' not in runner.reference(agent, pid)
        assert 'code' not in runner.reference(agent, pid)
        second_source = source.replace("'first'", "'second'")
        second = await call('cordis_define', plugin=dict(kind='existing', pluginId=pid), name='Second', purpose='Update', code=dict(host=second_source))
        assert second['packageId'] == 'pkg-2'
        inspected = await call('cordis_inspect_self', pluginId=pid)
        assert inspected['packageCount'] == 2
        assert [row['isCurrent'] for row in inspected['packages']] == [True, False]
        assert [row['isNext'] for row in inspected['packages']] == [False, False]
        assert runner.inspectPackage(agent, pid, 'pkg-1')['code']['host'] == source
        assert runner.reference(agent, pid)['packageId'] == 'pkg-1'
        message = create_user_message(dict(content=[dict(type='text', text='Please update @theme-1 @theme-1')], source=dict(kind='user')))
        async def next_fn(*_):
            return dict(kind='accept', messages=[], startsRequestSeries=True)
        payload = dict(agent=agent, messages=[message], signal=NEVER_ABORTED, turn=1, step=2)
        decision = await agent.ctx.waterfall('agent/pre-step', payload, next_fn)
        assert decision['startsRequestSeries'] is True
        references = [msg for msg in decision['messages'] if msg.get('source', {}).get('plugin') == 'tool-cordis']
        assert len(references) == 1
        injected = references[0]
        assert injected['id'] and injected['role'] == 'user'
        assert injected['source'] == dict(kind='plugin', plugin='tool-cordis', form='instructions')
        assert 'Use Package pkg-1 as the base' in injected['content'][0]['text']
        assert 'mode="update"' in injected['content'][0]['text']
        assert source not in injected['content'][0]['text']
        foreign_decision = await foreign.ctx.waterfall('agent/pre-step', dict(payload, agent=foreign), next_fn)
        foreign_reference = next(msg for msg in foreign_decision['messages'] if msg.get('source', {}).get('plugin') == 'tool-cordis')
        assert 'unavailable in the current Session' in foreign_reference['content'][0]['text']
        with pytest.raises(ValueError, match='packageId requires pluginId'):
            await call('cordis_inspect_self', packageId='pkg-2')
        await call('cordis_run', pluginId=pid, packageId=second['packageId'], mode='update')
        assert ctx.get('referenceProbe') == 'second'
        await call('cordis_stop', pluginId=pid)
        assert ctx.get('referenceProbe') is None
        assert await call('cordis_stop', pluginId=pid) == dict(pluginId=pid)
        assert (await call('cordis_inspect_self', pluginId=pid))['state'] == 'stopped'
        await call('cordis_undefine', pluginId=pid)
        removed = await agent.ctx.waterfall('agent/pre-step', payload, next_fn)
        removed_reference = next(msg for msg in removed['messages'] if msg.get('source', {}).get('plugin') == 'tool-cordis')
        assert 'unavailable in the current Session' in removed_reference['content'][0]['text']
        with pytest.raises(ValueError, match='dynamic plugin'):
            await call('cordis_run', pluginId=pid, packageId='pkg-2', mode='run')
        created = await call('cordis_define', plugin=dict(kind='new', idPrefix='panel'), name='Third', purpose='No reuse', code=dict(host=source))
        assert (created['pluginId'], created['packageId']) == ('panel-2', 'pkg-3')
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
