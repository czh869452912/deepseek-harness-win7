import json
from types import SimpleNamespace

import pytest

from scripts import rc022_plugin_tools_probe as corpus


@pytest.mark.asyncio
async def test_management_actions_approval_and_complete_guidance_tables(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'plugin-tool-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    by_name = {row['name']: row for row in rows}
    assert all(row['listeners'] == 0 for row in rows)
    assert by_name['plugins-page']['outcome']['value'] == dict(entries=[dict(name='bundle', rows=[dict(id='row')])], total=3, nextOffset=2)
    assert by_name['approval-rejected']['calls'][-1]['op'] == 'approval'
    assert 'error' in by_name['approval-rejected']['outcome']
    assert by_name['approval-allowed-once']['mode'] == 'read-only'
    assert by_name['apply-install_bundle']['calls'][-1] == dict(op='installBundle', args=['@fixture/plugin@1.0.0',
        dict(enabled=False, approvedBuilds=['build-one'], registry='https://registry.example')])
    assert by_name['apply-set_version_exemption']['calls'][-1]['args'] == ['@fixture/plugin@1.0.0', '0.2.2-rc.3', True, True]
    assert by_name['failure-network']['outcome']['value']['nextStep'] == corpus.DATA['FAILURE_STEPS']['network']
    assert by_name['error-management-required']['outcome']['value']['nextStep'] == corpus.DATA['ERROR_STEPS']['management-required']
    assert by_name['empty-page']['outcome']['value']['nextOffset'] is None


@pytest.mark.asyncio
async def test_loader_tool_registry_validation_approval_and_reversible_registration(tmp_path):
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.tools import ToolExecutionInput
    from scripts.rc022_candidate_fixture import setup
    mode, calls, approvals = ['danger-full-access'], [], []
    async def list_plugins():
        calls.append('list')
        return [dict(entryId='one', meta=dict(private=True))]
    def prepare(ctx):
        ctx.set_service('sandboxPolicy', SimpleNamespace(resolve=lambda options: dict(mode=mode[0])))
        ctx.set_service('pluginManager', SimpleNamespace(listPlugins=list_plugins))
    ctx = await setup(tmp_path, extra=[('plugin-manager/tools', {}, 'management-tools')], prepare=prepare)
    handle = await ctx.agents.create(dict(sessionId='tools', agentOptions=dict(provider='script', model='model')))
    async def call(identity, args):
        return await ctx.tools.execute(ToolExecutionInput(identity, 'plugin_manager', args, agent=handle.agent, signal=NEVER_ABORTED))
    try:
        assert ctx.tools.get('plugin_manager') is not None
        invalid = await call('invalid', dict(action='unknown'))
        assert invalid.is_error and invalid.error['info']['code'] == 'INVALID_ARGS' and calls == []
        listed = await call('listed', dict(action='list_plugins'))
        assert not listed.is_error
        assert json.loads(listed.value) == dict(entries=[dict(entryId='one')], total=1, nextOffset=None)
        assert listed.content == [dict(type='text', text=listed.value)]
        mode[0] = 'read-only'
        denied = await call('denied', dict(action='list_plugins'))
        assert denied.is_error and denied.error['info']['code'] == 'SANDBOX_ESCALATION_UNAVAILABLE' and calls == ['list']
        async def approve(request):
            approvals.append(request['callId'])
            return 'allowed-once'
        ctx.set_service('approval', SimpleNamespace(request=approve))
        approved = await call('approved', dict(action='list_plugins'))
        assert not approved.is_error and calls == ['list', 'list'] and approvals == ['approved']
        assert mode[0] == 'read-only'
        entry = next(item for item in ctx.loader.entries() if item.options.get('id') == 'management-tools')
        await entry.fiber.dispose()
        assert ctx.tools.get('plugin_manager') is None
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()
