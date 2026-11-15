import pytest
from scripts.rc022_initiators_probe import observe

@pytest.mark.asyncio
async def test_registry_local_initiators_drain_and_exclude_own_shutdown_lineage():
    rows=await observe()
    assert len(rows)==11
    for row in rows:
        if 'same' in row:assert row['same']
        if 'outside' in row:assert row['outside']==dict(value=None)
        if 'after' in row:assert row['after']==dict(error='agent initiator scope is disposed')
        if row['action']=='cross-registry':assert row['other']==dict(value=None) and row['own']==dict(value='a')
        if row['action']=='drain':assert row['state']=='closing' and row['hidden'] and row['waiting'] and row['with']==row['without']=='agent initiator scope is disposed'
        if row['action']=='async-unrelated':assert row['waiting'] and row['state']=='closing' and row['trace']==[dict(value='b'),dict(value='b')]

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',('override','python-future','rejected','cancelled','observer-failure'))
async def test_native_future_brand_observers_preserve_identity_and_release(kind):
    import asyncio
    from types import SimpleNamespace
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    class Overridden(asyncio.Future):
        def add_done_callback(self,*args,**kwargs):raise AssertionError('overridden observer called')
        def exception(self,*args,**kwargs):raise AssertionError('overridden exception getter called')
    ctx=Context();closed_loop=None
    try:
        await ctx.plugin(Registry);fiber=await ctx.plugin(CurrentAgentPlugin);service=ctx.get('agents')
        if kind=='observer-failure':
            closed_loop=asyncio.new_event_loop();future=closed_loop.create_future();future.set_result(True);closed_loop.close()
        elif kind=='python-future':future=asyncio.futures._PyFuture(loop=asyncio.get_running_loop())
        elif kind=='override':future=Overridden(loop=asyncio.get_running_loop())
        else:future=asyncio.get_running_loop().create_future()
        assert service.withInitiator(SimpleNamespace(id='future'),lambda:future) is future
        disposal=service.disposeInitiators();assert service.disposeInitiators() is disposal
        if kind!='observer-failure':
            assert not disposal.done()
            if kind=='rejected':future.set_exception(RuntimeError('observed rejection'))
            elif kind=='cancelled':future.cancel()
            else:future.set_result(True)
        await disposal
        assert service.initiatorState=='disposed'
        with pytest.raises(RuntimeError,match='scope is disposed'):service.currentInitiator()
        await fiber.dispose()
    finally:
        if closed_loop is not None and not closed_loop.is_closed():closed_loop.close()
        await ctx.fiber.dispose()
