from types import SimpleNamespace as NS

import pytest

from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.fs.fs_local import FsError
from dsh.fs.local_current import CurrentFsLocal
from dsh.fs.fs_observation_policy import CurrentFsObservationPolicy
from dsh.fs.tools_current import CurrentPatchToolFs
from dsh.fs.sandbox_tool_current import CurrentFsSandboxController
from scripts.rc022_subagent_fixture import setup
from scripts import rc022_patch_tool_probe as probe


@pytest.mark.asyncio
async def test_model_projection_and_replayed_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.engine, 'WORKSPACE', tmp_path)
    rows = await probe.observe()
    assert len(rows) == 62
    values = {row['name']: row for row in rows if row['name'] != 'replay'}
    assert values['syntax']['error']['code'] == 'PATCH_SYNTAX'
    assert values['independent-refusals']['error']['code'] == 'FS_NOT_OBSERVED'
    assert '2 problems' in values['independent-refusals']['error']['message']
    assert values['all-four']['render'].startswith('Success. Updated')
    assert 'before' not in str(values['all-four']['meta'].keys())
    assert values['move-remove-denied']['value']['operations'][1]['changes']
    assert 'source ' in values['move-remove-denied']['render']
    assert values['io-published']['value']['operations'][1]['status'] == 'unknown'
    assert values['preview-syntax']['value'] is None
    assert all(row['error'] is None for row in rows if row['name'] == 'replay')


@pytest.mark.asyncio
async def test_actual_agent_runtime_patch_scope_unload_and_current_directory(tmp_path):
    workspace = tmp_path/'workspace'; workspace.mkdir()
    fixture = await setup(tmp_path/'runtime', script=[], directory=workspace); ctx = fixture.ctx
    await ctx.plugin(CurrentFsLocal, dict(cwd=str(tmp_path)))
    await ctx.plugin(CurrentFsObservationPolicy)
    owner = await ctx.plugin(CurrentPatchToolFs, dict(applyPatch=True))
    lease = await ctx.agents.create(dict(sessionId='root', agentOptions=dict(provider='script', model='model')))
    agent = lease.agent
    async def call(name, arguments):
        return await ctx.tools.execute(ToolExecutionInput('patch-call', name, arguments, agent=agent, signal=NEVER_ABORTED))
    def sections(prompt):return {item['name']:item['text'] for item in prompt['sections']}
    try:
        patch = '*** Begin Patch\n*** Add File: a\n+old\n*** Update File: ./a\n@@\n-old\n+new\n*** End Patch'
        result = await call('apply_patch', dict(input=patch))
        assert not result.is_error, result.content
        assert result.value['operations'][1]['status'] == 'completed'
        assert (workspace/'a').read_bytes() == b'new\n' and not (tmp_path/'a').exists()
        edited = await call('edit', dict(file_path='a', old_string='new', new_string='edited'))
        assert not edited.is_error, edited.content
        removed = await call('apply_patch', dict(input='*** Begin Patch\n*** Delete File: a\n*** End Patch'))
        assert not removed.is_error and not (workspace/'a').exists()
        failure = await call('apply_patch', dict(input='invalid'))
        assert failure.is_error and failure.error['info']['code'] == 'PATCH_SYNTAX'
        invalid = await call('apply_patch', dict(input=123))
        assert invalid.is_error
        prompt = sections(await ctx.systemPrompt.assemble(dict(scope=agent)))
        assert 'whole patch' in prompt['tool:apply_patch']
        release = agent.ctx.tools.restrict(dict(deny=['apply_patch']))
        assert sections(await ctx.systemPrompt.assemble(dict(scope=agent)))['tool:apply_patch'] == ''
        release()
        await owner.dispose()
        assert ctx.tools.get('apply_patch', agent) is None
        assert 'tool:apply_patch' not in sections(await ctx.systemPrompt.assemble(dict(scope=agent)))
    finally:
        await lease.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('config,expected', [({}, {'read','write','edit'}), (dict(read=False,write=False,edit=False,readImage=False),set()), (dict(read=False,write=False,edit=False,applyPatch=True),{'apply_patch'})])
async def test_registration_selection_and_default_disabled(tmp_path, config, expected):
    fixture = await setup(tmp_path/'runtime', script=[]);ctx=fixture.ctx
    await ctx.plugin(CurrentFsLocal,dict(cwd=str(tmp_path)))
    try:
        owner=await ctx.plugin(CurrentPatchToolFs,config)
        assert {name for name in ('read','write','edit','apply_patch') if ctx.tools.get(name) is not None}==expected
        await owner.dispose()
        assert all(ctx.tools.get(name) is None for name in expected)
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_controller_repeated_mode_and_approval_before_directory_or_mutation(tmp_path):
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx;events=[]
    fs=NS(sandboxMode='read-only')
    ctx.set_service('fs',fs)
    ctx.set_service('sandboxPolicy',NS(resolve=lambda *_:dict(mode='read-only',workspaceRoot=str(tmp_path))))
    lease=await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))
    async def approval(request):events.append(request);return 'allowed-once'
    ctx.set_service('approval',NS(request=approval));execution=NS(agent=lease.agent,signal=NEVER_ABORTED,callId='call')
    controller=CurrentFsSandboxController(ctx)
    try:
        repeated=await controller.resolve_policy('apply_patch',dict(sandbox_permissions='read-only'),execution)
        assert repeated['mode']=='read-only' and events==[]
        assert (await controller.resolve_policy('edit',dict(justification=' \ufeff '),execution))['mode']=='read-only'
        approved=await controller.resolve_policy('apply_patch',dict(sandbox_permissions='workspace-write',justification='这次写入需要权限'),execution)
        assert approved['mode']=='workspace-write' and len(events)==1
        assert events[0]['displayReason']['zh'].endswith('这次写入需要权限')
        assert events[0]['toolName']=='apply_patch'
        with pytest.raises(Exception) as failure:
            await controller.resolve_policy('write',dict(justification='unpaired'),execution)
        assert failure.value.code=='SANDBOX_ESCALATION_INVALID_ARGUMENT'
        error=FsError('provider detail','FS_SANDBOX_DENIED');mapped=controller.map_error(error,repeated)
        assert mapped.code==error.code and mapped.cause is error and '[sandbox:' in mapped.message
    finally:await lease.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_confined_patch_retries_only_after_approval(tmp_path):
    from dsh.sandbox.policy_current import CurrentSandboxPolicy
    from dsh.fs.sandbox_current import CurrentFsSandbox
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx;events=[]
    async def ensure(*_):events.append('directory');return str(tmp_path)
    ctx.workingDirectory.ensure=ensure
    await ctx.plugin(CurrentSandboxPolicy,dict(mode='read-only',workspaceRoot=str(tmp_path)))
    await ctx.plugin(CurrentFsSandbox,dict(cwd=str(tmp_path)))
    await ctx.plugin(CurrentFsObservationPolicy)
    await ctx.plugin(CurrentPatchToolFs,dict(applyPatch=True))
    lease=await ctx.agents.create(dict(sessionId='confined',agentOptions=dict(provider='script',model='model')))
    patch='*** Begin Patch\n*** Add File: confined\n+approved\n*** End Patch'
    async def call(**args):return await ctx.tools.execute(ToolExecutionInput('call','apply_patch',dict(input=patch,**args),agent=lease.agent,signal=NEVER_ABORTED))
    try:
        denied=await call()
        assert denied.is_error and denied.error['info']['code']=='FS_SANDBOX_DENIED'
        assert not (tmp_path/'confined').exists()
        events.clear()
        async def rejected(_):events.append('approval');return 'rejected'
        ctx.set_service('approval',NS(request=rejected))
        rejected_result=await call(sandbox_permissions='workspace-write',justification='Allow this exact patch')
        assert rejected_result.is_error and rejected_result.error['info']['code']=='SANDBOX_ESCALATION_REJECTED'
        assert events==['approval'] and not (tmp_path/'confined').exists()
        events.clear()
        async def allowed(_):events.append('approval');return 'allowed-once'
        ctx.set_service('approval',NS(request=allowed))
        approved=await call(sandbox_permissions='workspace-write',justification='Allow this exact patch')
        assert not approved.is_error, approved.content
        assert events[0]=='approval' and 'directory' in events[1:]
        assert (tmp_path/'confined').read_bytes()==b'approved\n'
        assert ctx.sandboxPolicy.resolve(dict(session=lease.agent.session))['mode']=='read-only'
    finally:await lease.dispose();await ctx.fiber.dispose()
