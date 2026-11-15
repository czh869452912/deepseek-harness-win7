import asyncio
from types import SimpleNamespace as NS
import pytest
from scripts.rc022_subagent_lifetime_probe import observe


@pytest.mark.asyncio
async def test_interrupt_and_resource_settlement_contracts():
    rows=await observe()
    interrupt={row['action']:row for row in rows if row['kind']=='interrupt'}
    assert interrupt['root']['trace']==[dict(cancel=dict(kind='parent'),options=dict(keepInbox=True))]
    assert interrupt['user']['trace']==[dict(cancel=dict(kind='user'),options=dict(keepInbox=True))]
    assert interrupt['absent']['trace']==[] and interrupt['closing']['trace']==[]
    for action in ('outsider','stale','self'):assert interrupt[action]['error']['code']=='UNAUTHORIZED'
    disposals={row['action']:row for row in rows if row['kind']=='dispose'}
    assert all(row['same'] and row['cutoff'] and row['descendantSame'] for row in disposals.values())
    assert disposals['handle-failure']['result']['stopReason']=='completed'
    assert disposals['handle-failure']['error']=='ACTIVATION_TEARDOWN_FAILED'
    assert disposals['external-result-failure']['resultErrorSame']
    assert next(row for row in rows if row['kind']=='readiness')['states']==['ready','wait','ready','retry','closed']


async def setup():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.subagent.lifetime import SubagentLifetime
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context()
    for plugin in (CurrentLlmRuntime,Store,Projections,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):
        await ctx.plugin(plugin)
    await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
    root=(await ctx.agents.create(dict(sessionId='root'))).agent
    edges=[]
    lifetime=SubagentLifetime(ctx,NS(identityOf=lambda session:None,emitLifecycle=lambda *args:edges.append(args)),lambda:2)
    return ctx,root,lifetime,edges


async def child_activation(lifetime,root):
    from dsh.subagent.lifetime import future,contain
    from dsh.subagent.activation import observe_local_failure
    handle=await lifetime.owner_ctx.get('agents').create(dict(sessionId='child',meta=dict(parentSession='root',origin='subagent')))
    a=NS(kind='local',childId='child',runId='run',provider='test',root=root,ancestors=['root'],path='worker',
        handle=handle,outputStart=handle.agent.session.seq,structured=None,failureAt=None,poke=future(),omitClosingText=False,
        releaseSlot=lifetime.root_pool(root).reserve(2),result=contain(future()),closing=None,accepted=False,delivery='caller')
    lifetime.resident[a.childId]=a
    observe_local_failure(a,lambda:lifetime.wake(a))
    for event in ('agent/inbox/inserted','agent/inbox/claimed','agent/inbox/discarded'):
        handle.agent.ctx.on(event,lambda *args:lifetime.wake(a))
    return a


@pytest.mark.asyncio
async def test_real_idle_agent_with_parked_input_stays_resident_until_input_clears():
    from dsh.llm.message import create_user_message
    ctx,root,lifetime,edges=await setup()
    try:
        a=await child_activation(lifetime,root)
        child=a.handle.agent
        child.inject(create_user_message(dict(content=[dict(type='text',text='parked')])))
        lifetime.accept(a)
        assert await lifetime.wait_for_tree_work(root) is False
        lifetime.interrupt('child',dict(kind='ancestor',agent=root))
        assert len(child.inbox.nextStep)==1 and a.closing is None
        child.inbox.clear()
        result=await asyncio.wait_for(asyncio.shield(a.result),3)
        assert result==dict(output=[],stopReason='aborted')
        assert ctx.agents.get('child') is None and 'child' not in lifetime.resident
        assert len(edges)==1 and edges[0][0]=='subagent/end'
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_final_flush_race_rechecks_new_input_before_closing():
    from dsh.llm.message import create_user_message
    ctx,root,lifetime,edges=await setup()
    entered,release=asyncio.Event(),asyncio.Event()
    original=lifetime.flush_final_state
    count=0
    async def flush(a):
        nonlocal count
        count+=1
        if count==1:
            entered.set();await release.wait()
        await original(a)
    lifetime.flush_final_state=flush
    try:
        a=await child_activation(lifetime,root);lifetime.accept(a)
        await asyncio.wait_for(entered.wait(),3)
        a.handle.agent.inject(create_user_message(dict(content=[dict(type='text',text='new input')])))
        release.set()
        assert await lifetime.wait_for_tree_work(root) is False
        assert not a.result.done() and a.closing is None
        a.handle.agent.inbox.clear()
        await asyncio.wait_for(asyncio.shield(a.result),3)
        assert count>=2 and len(edges)==1
    finally:
        release.set();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_scoped_drain_waits_for_owned_startup_and_preserves_other_tree():
    from dsh.core.abort import NEVER_ABORTED
    from dsh.subagent.errors import SubagentError
    ctx,root,lifetime,edges=await setup()
    try:
        other=(await ctx.agents.create(dict(sessionId='other'))).agent
        async def blocked(signal):
            await signal.wait_aborted()
            signal.throwIfAborted()
        pending=lifetime.track_startup(root,NEVER_ABORTED,blocked)
        release=asyncio.Event()
        async def independent(signal):await release.wait();return 'other result'
        other_pending=lifetime.track_startup(other,NEVER_ABORTED,independent)
        drain=lifetime.drain_descendants([root])
        with pytest.raises(SubagentError,match='draining'):lifetime.assert_admitting(root)
        lifetime.assert_admitting(other)
        await asyncio.wait_for(drain,3)
        with pytest.raises(SubagentError) as error:await pending
        assert error.value.code=='DRAINING' and not other_pending.done()
        release.set();assert await other_pending=='other result'
        assert lifetime.materializations==set()
    finally:await ctx.fiber.dispose()
