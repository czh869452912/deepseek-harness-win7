import pytest
from scripts.rc022_child_composition_probe import observe


@pytest.mark.asyncio
async def test_policy_preset_and_structured_boundaries():
    rows=await observe()
    policies=[row for row in rows if row['kind']=='policy']
    assert [row['captured'].get('permissionPreset') for row in policies]==[None,None,'auto','danger-full-access']
    assert all(row['selected']['agentPreset']=='other' and row['inherited']['agentPreset']=='live-parent' for row in policies)
    structured={row['action']:row for row in rows if row['kind']=='structured'}
    assert structured['pending-input']['states']==[True,True]
    assert structured['nested-success']['states']==[True,False,False,False]
    assert structured['nested-error']['states']==[True,False,False,True]
    assert structured['direct-error']['captured'] is None


@pytest.mark.asyncio
async def test_actual_tools_pipeline_reopens_failed_attempt_and_closes_after_commit():
    from dsh.cordis import Context
    from dsh.core.tools import ToolsService,ToolExecutionInput
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.subagent.structured import attach_structured_runtime
    ctx=Context();tools=ToolsService(ctx,contract_version=4);ctx.set_service('tools',tools)
    pending=True
    try:
        await ctx.plugin(CurrentSystemPrompt)
        attachment=attach_structured_runtime(ctx,dict(type='object',properties=dict(ok=dict(type='boolean')),required=['ok']),lambda:not pending)
        def request(identity):
            return ToolExecutionInput(identity,'structured_output',dict(ok=True),signal=NEVER_ABORTED)
        rejected=await tools.execute(request('pending'))
        assert rejected.isError and attachment.acceptsInput()
        assert 'Process pending messages' in rejected.content[0]['text']
        pending=False
        success=await tools.execute(request('accepted'))
        assert not success.isError and attachment.captured()==dict(value=dict(ok=True))
        assert not attachment.acceptsInput() and success.concludes_turn
        duplicate=await tools.execute(request('duplicate'))
        assert duplicate.isError and not duplicate.concludes_turn
    finally:await ctx.fiber.dispose()
    assert tools.get_tool('structured_output') is None
