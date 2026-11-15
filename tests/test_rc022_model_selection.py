import pytest
from scripts.rc022_model_selection_probe import observe

@pytest.mark.asyncio
async def test_model_fold_notices_and_fixed_request_boundaries():
    rows=await observe()
    assert len(rows)==32
    for row in rows:
        test=row['test']
        if test['operation']=='model':
            assert row['duplicateSkipped'] and row['sameState']
            assert row['detached']['model']=='b1' and row['retained']==row['cold']
            if not test['defaulted'] or test['effort'] is None:assert row['state']['pending'] is None
            else:assert row['state']['pending']['reasoningEffort']==test['effort']
        elif test['operation']=='notice' and test['kind'] in ('changed','same-provider','long','empty-continuation'):
            message=row['decision']['messages'][-1]
            assert message['source']['kind']=='model-selection'
            assert len(message['source']['summary'])<=120
        elif test['operation']=='request':
            if test['kind'] in ('route-change','effort-change','effort-add','effort-drop'):assert 'use agent.model.select()' in row['error']
            else:
                assert row['config']['provider']=='alpha' and row['config']['model']=='a0'
                assert 'reasoningEffort' not in row['config']

@pytest.mark.asyncio
async def test_actual_v4_loop_holds_step_choice_then_consumes_later_selection():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import ToolsPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context();handle=None;seen=[];requests=[]
    try:
        for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,ToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        ctx.get('llm').registerAdapter(['script'],ScriptAdapter(dict(script=[response() for _ in range(4)])))
        ctx.on('llm/stream',lambda request,next_fn:(requests.append(request),next_fn())[1])
        async def before(input,next_fn):
            seen.append(dict(input['modelSelection']))
            if len(seen)==1:input['agent'].model.select(dict(provider='script',model='later'))
            return await next_fn()
        ctx.on('agent/pre-step',before)
        handle=await ctx.get('agents').create(dict(sessionId='actual-model',options=dict(provider='script',model='initial')))
        agent=handle.agent;agent.followup(message('first'));await agent.whenIdle()
        assert requests[0]['model']=='initial'
        assert agent.model.current()==dict(provider='script',model='later')
        agent.followup(message('second'));await agent.whenIdle()
        assert requests[-1]['model']=='later'
        state=ctx.get('sessionProjections').snapshot(agent.session)['values']['modelSelection']
        assert state==dict(lastUsed=dict(provider='script',model='later'),next=dict(provider='script',model='later'))
        assert seen[0]['model']=='initial' and any(choice['model']=='later' for choice in seen[1:])
    finally:
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()
