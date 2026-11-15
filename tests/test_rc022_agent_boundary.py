import pytest
from scripts.rc022_agent_boundary_probe import observe

@pytest.mark.asyncio
async def test_agent_owns_boundary_handle_before_loop_and_after_release():
    for row in await observe():
        if row['action']=='deferred':
            assert row['waiting']==1 and row['ready']==2
            continue
        assert row['initial']['lastTurn']==0 and row['initial']['openTurnStartSeq'] is None
        assert row['open']==dict(openTurnStartSeq=0,lastStepStartSeq=1,lastStepBoundary=dict(kind='start',seq=1),lastTurn=3)
        assert row['closed']==dict(openTurnStartSeq=None,lastStepStartSeq=1,lastStepBoundary=dict(kind='end',seq=2),lastTurn=3)
        assert row['released']==row['checkpoint'] and row['unread']=={}
        assert row['retained']['lastTurn']==4 and row['retained']['openTurnStartSeq']==4
        if row['action']=='replacement':
            assert row['replacement']==row['retained']
            assert row['newCheckpoint']['turnBoundary']['ver']==2 and row['newCheckpoint']['turnBoundary']['seq']==4


@pytest.mark.asyncio
async def test_v4_loop_borrows_agent_boundary_without_registering_it_again():
    from types import SimpleNamespace
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopService
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context()
    try:
        await ctx.plugin(Store);await ctx.plugin(Registry);agent_owner=await ctx.plugin(CurrentAgentPlugin)
        registry=ctx.get('sessionProjections');session=ctx.get('sessions').create('loop-boundary')
        session.append('turn/start',dict(turn=8))
        def forbidden(*args,**kwargs):raise AssertionError('loop tried to register turnBoundary')
        registry.register=forbidden
        loop=CurrentAgentLoopService(ctx,dict(agents=[]))
        assert loop._get_turn_number(SimpleNamespace(session=session))==9
        await agent_owner.dispose()
        assert not registry.has('turnBoundary')
        assert registry.checkpoint(session)['turnBoundary']['val']['lastTurn']==8
        await loop.teardown()
    finally:await ctx.fiber.dispose()
