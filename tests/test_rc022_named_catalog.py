import pytest
from scripts.rc022_named_catalog_probe import observe


@pytest.mark.asyncio
async def test_named_child_admission_and_all_catalog_generations():
    rows = await observe()
    names = {row['value']:row['valid'] for row in rows if row['kind'] == 'name'}
    assert names['a'*32] and not names['a'*33] and not names['lead'] and not names['a\n']
    facts = [row for row in rows if row['kind'] == 'fact']
    assert all(row['inheritedSame'] for row in facts)
    assert sum(row['accepted'] for row in facts) == 8
    assert all(row['previousSame'] and row['detached'] for row in facts if row['accepted'])
    reservation = next(row for row in rows if row['kind'] == 'reservations')
    assert reservation['names'] == ['agent-2', 'agent-3', 'agent-2', 'agent-2', 'agent-2']
    assert next(row for row in rows if row['kind'] == 'stale-pool')['names'] == ['agent-1', 'agent-2']
    assert next(row for row in rows if row['kind'] == 'released')['name'] == 'agent-1'
    assert next(row for row in rows if row['kind'] == 'chunks') == dict(kind='chunks', capacity=62,count=190,shared=True,names=['worker'])
    assert all(not row['accepted'] for row in rows if row['kind'] == 'checkpoint')


@pytest.mark.asyncio
async def test_actual_v4_projection_retains_old_unnamed_and_new_named_facts():
    from dsh.cordis import Context
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.subagent.catalog import CATALOG
    ctx = Context()
    store = CurrentSessionStore(ctx, 4)
    registry = SessionProjectionRegistry(ctx, 4)
    try:
        handle = await registry.register(CATALOG)
        session = store.create('parent')
        session.append('subagent/catalog', dict(version=1,childId='old',childCreatedAt=1,mode='unknown'))
        session.append('subagent/catalog', dict(version=3,childId='new',childCreatedAt=2,mode='continuable',label='Task',name='worker'))
        assert registry.snapshot(session)['values']['subagentCatalog'] == [dict(id='old',createdAt=1,mode='unknown'),dict(id='new',createdAt=2,mode='continuable',label='Task',name='worker')]
        state = handle.stateOf(session)
        assert CATALOG['stateSchema'](state) == state
        assert handle is not None and CATALOG['stateVersion'] == 6
    finally:
        await ctx.fiber.dispose()
