import asyncio
from types import SimpleNamespace as NS
import pytest
from scripts.rc022_control_tools_probe import observe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_real_control_tools_and_wait_resource_contracts(tmp_path):
    rows=await observe(tmp_path)
    calls=[row for row in rows if row['kind']=='call']
    assert calls[0]['result']['value']==calls[1]['result']['value']
    assert [entry['name'] for entry in calls[0]['result']['value']]==['lead','a','b','b/leaf']
    assert calls[2]['result']['value']==dict(messageId='<message>')
    assert calls[4]['result']['isError'] and calls[5]['result']['value']==dict(accepted=True)
    assert calls[-1]['result']['value'][-1]['status']=='inactive'
    identities=[row['text'] for row in rows if row['kind']=='identity']
    assert '"b/leaf"' in identities[2] and identities[3]=='' and 'root is unavailable' in identities[-1]
    waits={row['name']:row for row in rows if row['kind']=='wait'}
    assert all(row['timers']==0 and row['listenersReleased'] for row in waits.values())
    assert waits['same-call-timeout']['result']['value']==dict(timedOut=True)
    for name in ('pending','new-input-same-call','new-call-pending','arrival','unrelated-then-own'):
        assert waits[name]['result']['value']==dict(timedOut=False)
    for name in ('cancel','disposed','unloaded'):assert waits[name]['result']['isError']
    assert next(row for row in rows if row['kind']=='unrelated')['pending']
    assert rows[-2]['names']==['list_agents','send_message','wait_agent'] and rows[-1]['text']==''


@pytest.mark.asyncio
async def test_input_wait_preserves_exact_abort_error_and_pending_input(tmp_path):
    from dsh.core.abort import AbortController
    from dsh.subagent.wait_input import InputWaits
    fixture=await setup(tmp_path);ctx=fixture.ctx
    try:
        parent=(await ctx.agents.create(dict(sessionId='root'))).agent
        waits=InputWaits(ctx);controller=AbortController();reason=RuntimeError('exact cancellation')
        task=asyncio.create_task(waits.execute({},NS(agent=parent,signal=controller.signal,rootCallId='call')))
        await asyncio.sleep(0);controller.abort(reason)
        with pytest.raises(RuntimeError) as captured:await task
        assert captured.value is reason
        assert not parent.inbox.nextStep
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_team_task_changes_do_not_wake_or_insert_input(tmp_path):
    from dsh.team.service import TeamPlugin
    from dsh.subagent.wait_input import InputWaits
    from dsh.llm.message import create_user_message
    fixture=await setup(tmp_path);ctx=fixture.ctx
    try:
        await ctx.plugin(TeamPlugin)
        parent=(await ctx.agents.create(dict(sessionId='root'))).agent
        waits=InputWaits(ctx)
        task=asyncio.create_task(waits.execute({},NS(agent=parent,signal=fixture.signal,rootCallId='call')))
        await asyncio.sleep(0)
        await ctx.agentTeams.setEnabled(parent,True)
        await ctx.agentTeams.createTask(parent,dict(subject='Task',description='Details'))
        await asyncio.sleep(0)
        assert not task.done() and not parent.inbox.nextStep
        parent.inject(create_user_message(dict(content=[dict(type='text',text='new input')])))
        assert await asyncio.wait_for(task,1)==dict(timedOut=False)
        assert len(parent.inbox.nextStep)==1
    finally:await ctx.fiber.dispose()
