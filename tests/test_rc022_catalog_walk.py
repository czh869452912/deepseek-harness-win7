import pytest
from scripts.rc022_catalog_walk_probe import observe


@pytest.mark.asyncio
async def test_catalog_traversal_releases_every_read_and_separates_branch_failures():
    rows = {row['action']:row for row in await observe()}
    assert all(row['active'] == 0 and row['peak'] <= 1 for row in rows.values())
    tree = rows['walk']['value']
    assert [row['id'] for row in tree] == ['a','nested','ext','old','legacy-nested']
    assert [row.get('path') for row in tree] == ['alpha','alpha/nested','external',None,None]
    assert tree[0]['activity'] == 'running' and tree[0]['hasChildren']
    assert tree[3]['reason'] == 'unsupported'
    assert rows['direct']['same']
    assert rows['path']['value'] == 'nested'
    assert rows['path']['trace'] == ['read:root','dispose:root','read:a','dispose:a']
    assert rows['external-path']['value'] is None
    assert rows['invalid-path']['trace'] == []
    assert rows['root-error']['error']['same']
    assert rows['branch-corrupt']['value'][0]['reason'] == 'corrupt'
    assert rows['branch-unavailable']['value'][0]['reason'] == 'unavailable'
    for action in ('abort-before','abort-root','abort-branch'):
        assert rows[action]['error']['code'] == 'CANCELLED'
    assert rows['subagent-error']['error'] == dict(code='DOMAIN_FAILURE',same=True)


@pytest.mark.asyncio
async def test_actual_query_uses_catalog_edges_and_keeps_ordinary_forks_out():
    from dsh.cordis import Context
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.session.query_current import CurrentSessionQueryService
    from dsh.subagent.catalog import CATALOG
    from dsh.subagent.list_children import list_descendants
    ctx = Context()
    store = CurrentSessionStore(ctx, 4)
    registry = SessionProjectionRegistry(ctx, 4)
    try:
        await registry.register(CATALOG)
        ctx.set_service('sessionQuery', CurrentSessionQueryService(ctx))
        parent = store.create('parent')
        store.create('child', dict(meta=dict(parentSession='parent',origin='subagent')))
        store.create('ordinary-fork', dict(meta=dict(parentSession='parent')))
        assert await list_descendants(ctx, 'parent') == []
        parent.append('subagent/catalog', dict(version=3,childId='child',childCreatedAt=1,mode='continuable',label='Task',name='worker'))
        result = await list_descendants(ctx, 'parent')
        assert [row['id'] for row in result] == ['child']
        assert result[0]['path'] == 'worker' and result[0]['activity'] == 'running'
    finally:
        await ctx.fiber.dispose()
