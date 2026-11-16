import json

import pytest

from dsh.boot.plugin_registry import _load
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.typert.artifact import read_generated_artifact
from scripts.rc022_candidate_fixture import setup
from test_rc022_manager_wire import http, SOURCE


@pytest.mark.asyncio
async def test_loader_declarative_presets_actual_remote_selection_and_tool_visibility(tmp_path):
    plugin = '@deepseek-ai/dsh-tool-working-directory'
    extra = [('agent-preset-registry', dict(default='coding')),
        ('agent-preset', dict(id='coding', name='Coding', plugins=[dict(id='working-directory-tool', name=plugin)]), 'preset-coding'),
        ('agent-preset', dict(id='review', name='Review', plugins=[]), 'preset-review'),
        ('client-ui-plugin-manager', dict(registryProbeEnabled=False)),
        ('typert-registry', {}), ('api-remote-access', {}), ('api-gateway', dict(websocketCompression='none')),
        ('api-remotes', {}), ('credentials-local', dict(path=str(tmp_path/'credentials.yaml'))),
        ('client-connection', {}), ('host-webserver', dict(host='127.0.0.1', port=0))]
    def prepare(ctx):
        ctx.loader.harness_plugins[plugin] = _load(plugin, CURRENT_HARNESS_PLUGIN_CLASSES[plugin])
        for artifact in ('preset/agent-preset-registry', 'client/ui-plugin-manager'):
            path = SOURCE/('packages/'+artifact+'/lib/typert.host.js')
            ctx.inject(['typert'], lambda child, path=path: child.effect(lambda: child.typert.register(read_generated_artifact(path))))
    ctx = await setup(tmp_path, extra=extra, prepare=prepare); lease = None; observations = []
    async def rpc(endpoint, args):
        response = await http(ctx.webServer, '/api/'+endpoint, dict(type='client-request', rpcId=endpoint, method=endpoint, payload=dict(args=args)), cookie)
        assert response['status'] == 200, response
        result = json.loads(response['body'])['result']; observations.append(dict(endpoint=endpoint, result=result))
        assert 'error' not in result, result
        return result.get('value')
    try:
        response = await http(ctx.webServer, '/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        assert response['status'] == 302, response
        cookie = response['headers']['set-cookie'].split(';')[0]
        catalog = await rpc('agentPresets/list', {})
        assert {row['id'] for row in catalog['presets']} == {'coding', 'review'}
        assert next(row for row in catalog['presets'] if row['id'] == 'coding')['isDefault']
        document = await rpc('agentPresets/read', dict(agentPreset='coding'))
        assert plugin in document['content']
        assert await rpc('pluginRegistryProbe/fastest', {}) is None
        async def compose(child, agent): await ctx.agentPresets.mount(child, 'coding')
        lease = await ctx.agents.create(dict(sessionId='owner', agentOptions=dict(provider='script', model='m'), setup=compose))
        assert 'working_directory' in [tool['name'] for tool in ctx.tools.schemas(lease.agent)]
        result = await ctx.tools.execute(ToolExecutionInput('cwd', 'working_directory', {}, agent=lease.agent, signal=NEVER_ABORTED))
        assert not result.is_error, result.error
        assert result.value == dict(cwd=str(tmp_path))
        assert await rpc('agentPresets/select', dict(agentId='owner', agentPreset='review')) == 'review'
        assert 'working_directory' not in [tool['name'] for tool in ctx.tools.schemas(lease.agent)]
        assert ctx.agentPresets.projection.stateOf(lease.agent.session) == 'review'
        assert await rpc('agentPresets/select', dict(agentId='owner', agentPreset='coding')) == 'coding'
        assert 'working_directory' in [tool['name'] for tool in ctx.tools.schemas(lease.agent)]
        (tmp_path/'preset-wire-observations.json').write_text(json.dumps(dict(remote=observations, tool=result.value), indent=2), encoding='utf-8')
    finally:
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
