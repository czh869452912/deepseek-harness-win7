"""Cordis tools exercise the real, shared, session-owned Host runner."""
import pytest
from types import SimpleNamespace
from canonical_web_fixture import web_context, close_web_context
from dsh.core.abort import NEVER_ABORTED


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
