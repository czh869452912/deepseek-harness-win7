import pytest
from scripts.rc022_subagent_timing_probe import observe


@pytest.mark.asyncio
async def test_completion_reset_and_fork_capture_contracts():
    rows = await observe()
    timelines = [row['steps'] for row in rows if row['kind'] == 'timeline']
    assert timelines[1][0]['same'] == [True,True]
    assert timelines[3][-1]['values'][0] == dict(settledMs=7,lastTurnCompleted=True)
    assert timelines[4][-1]['values'][0] == dict(settledMs=5,lastTurnCompleted=False)
    assert timelines[5][-1]['same'] == [True,True]
    assert timelines[6][-1]['values'][0] == dict(settledMs=6,lastTurnCompleted=True)
    assert timelines[7][4]['values'][1] is None
    assert timelines[8][-1]['values'][1] is None
    assert [row['valid'] for row in rows if row['kind']=='schema'] == [False,True,True,False,False,True,False,False,False,False,True,False]
    forks = [row for row in rows if row['kind']=='fork']
    assert all(row['unchanged'] for row in forks)
    assert [len(row['spec'].get('seed',[])) for row in forks] == [0,0,3,3,3]


@pytest.mark.asyncio
async def test_actual_factory_seed_and_own_descriptor_reset_are_separate():
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
    from dsh.subagent.projections import TIMING4, IDENTITY
    from dsh.subagent.in_process import InProcessProvider
    class Store(Plugin):
        def apply(self,ctx): CurrentSessionStore(ctx,4)
    class Projections(Plugin):
        def apply(self,ctx): SessionProjectionRegistry(ctx,4)
    ctx = Context()
    try:
        for plugin in (CurrentLlmRuntime,Store,Projections,CurrentSystemPrompt,CurrentToolsPlugin,
                       NativeToolExecutorPlugin,CurrentAgentPlugin):
            await ctx.plugin(plugin)
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        timing = await ctx.sessionProjections.register(TIMING4)
        identity = await ctx.sessionProjections.register(IDENTITY)
        parent = (await ctx.agents.create(dict(sessionId='parent'))).agent
        parent.session.append('turn/start',dict(turn=1))
        parent.session.append('subagent/descriptor',dict(version=3,mode='continuable',provider='spawn',label='Ancestor'))
        parent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        parent.session.append('turn/start',dict(turn=2))
        prepared = await InProcessProvider('fork',True).prepareContinuable(dict(parent=parent))
        child = (await ctx.agents.create(dict(sessionId='child',seed=prepared['seed'],inheritedEventCount=3,
            meta=dict(isSeeded=True,parentSession='parent',origin='subagent')))).agent
        inherited = identity.stateOf(child.session)['identity']
        assert inherited['label']=='Ancestor' and not child.session.isOwnSeq(inherited['seq'])
        assert child.session.inheritedEventCount==3
        assert child.session.events[3]['type']=='session/end-seed'
        child.session.append('turn/start',dict(turn=1))
        own = child.session.append('subagent/descriptor',dict(version=3,mode='continuable',provider='fork',label='Child'))['seq']
        assert identity.stateOf(child.session)['identity']==dict(mode='continuable',label='Child',seq=own)
        assert child.session.isOwnSeq(own)
        assert 'lastTurnCompleted' not in timing.stateOf(child.session)
        assert timing.stateOf(child.session)['settledMs']==0
        child.session.append('turn/end',dict(turn=1,reason=dict(kind='cancelled')))
        assert timing.stateOf(child.session)['lastTurnCompleted'] is False
        # The captured seed does not grow when its parent's in-flight turn closes.
        parent.session.append('turn/end',dict(turn=2,reason=dict(kind='completed')))
        assert len(prepared['seed'])==3
    finally:
        await ctx.fiber.dispose()
