import asyncio
import pytest
from dsh.core.session import SessionHeader
from dsh.core.abort import AbortController
from dsh.session.projections import SessionProjectionsPlugin
from dsh.subagent.projections import IDENTITY, TIMING
from dsh.subagent.descriptor import snapshot_descriptor
from dsh.subagent.errors import SubagentError
from test_subagent_continuation import mounted, retired


@pytest.mark.asyncio
async def test_catalog_reads_cold_children_without_agents_and_traverses_ordinary_nodes(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    try:
        await ctx.plugin(SessionProjectionsPlugin)
        registry = ctx.get('sessionProjections')
        registry.register(IDENTITY)
        registry.register(TIMING)
        await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='work')))
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        persisted = ctx.get('sessionPersistence')
        await persisted.create(SessionHeader('ordinary', parent_session='parent', created_at=100))
        await persisted.append('ordinary', [dict(type='session/title', seq=0, time=100, data=dict(title='ordinary'))])
        await persisted.create(SessionHeader('descendant', parent_session='ordinary', origin='subagent', created_at=101))
        await persisted.append('descendant', [dict(type='subagent/descriptor', seq=0, time=101,
            data=snapshot_descriptor(dict(mode='continuable', provider='spawn', label='deep child')))])
        listed = await manager.host.listChildren('parent')
        assert listed == [dict(kind='child', id='worker', mode='continuable', label='worker', activity='inactive', hasChildren=False)]
        tree = await manager.host.listDescendants('parent')
        assert [row['id'] for row in tree] == ['descendant', 'worker']
        assert tree[0]['depth'] == 2 and tree[0]['parentId'] == 'ordinary'
        assert ctx.get('agents').get('descendant') is None and ctx.get('sessions').get('worker') is None
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_bad_identity_resets_projection_and_listing_isolates_corruption(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    try:
        with pytest.raises(SubagentError) as error:
            await manager.host.listChildren('parent')
        assert error.value.code == 'SUBAGENT_CONTROL_PROJECTIONS_UNAVAILABLE'
        await ctx.plugin(SessionProjectionsPlugin)
        registry = ctx.get('sessionProjections')
        registry.register(IDENTITY)
        registry.register(TIMING)
        session = ctx.get('sessions').create('damaged', {'meta': {'parentSession': 'parent', 'origin': 'subagent'}})
        # Use an explicit factory-independent header to verify projection behavior.
        session.append('subagent/descriptor', snapshot_descriptor(dict(mode='continuable', provider='spawn', label='valid')))
        assert registry.snapshot(session)['values']['subagent']['label'] == 'valid'
        session.append('subagent/descriptor', {'version': 99})
        assert registry.snapshot(session)['values']['subagent'] is None
        abort = AbortController()
        abort.abort('stop')
        with pytest.raises(SubagentError) as error:
            await manager.host.listChildren('parent', abort.signal)
        assert error.value.code == 'CANCELLED'
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()


def test_timing_resets_at_own_descriptor_and_rejects_invalid_checkpoint():
    state = TIMING['init'](None)
    for kind, stamp in [('turn/start', 1), ('subagent/descriptor', 2), ('turn/end', 10),
                        ('subagent/descriptor', 11), ('turn/start', 12), ('turn/end', 17)]:
        state = TIMING['apply'](state, dict(type=kind, time=stamp))
    assert TIMING['wire']['view'](state) == {'settledMs': 5}
    with pytest.raises(ValueError):
        TIMING['stateSchema'](dict(state, settledMs=-1))
    with pytest.raises(ValueError):
        IDENTITY['stateSchema']({'identity': None})


@pytest.mark.asyncio
async def test_cold_catalog_bounds_observations_and_isolates_bad_child(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    try:
        await ctx.plugin(SessionProjectionsPlugin)
        ctx.get('sessionProjections').register(IDENTITY)
        persistence = ctx.get('sessionPersistence')
        for index in range(9):
            sid = 'child-' + str(index)
            await persistence.create(SessionHeader(sid, parent_session='parent', origin='subagent', created_at=index))
            descriptor = snapshot_descriptor(dict(mode='continuable', provider='spawn', label=sid)) if index < 8 else {'version': 99}
            await persistence.append(sid, [dict(type='subagent/descriptor', seq=0, time=index, data=descriptor)])
        query = ctx.get('sessionQuery')
        original = query.observeSession
        active, peak = 0, 0
        async def observe(sid, options=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.001)
                return await original(sid, options)
            finally:
                active -= 1
        query.observeSession = observe
        rows = await manager.host.listChildren('parent')
        assert len(rows) == 9 and peak == 4
        assert rows[-1] == dict(kind='diagnostic', id='child-8', reason='corrupt')
        assert all(row['kind'] == 'child' for row in rows[:-1])
        assert ctx.get('agents').list() == [parent.agent]
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()

