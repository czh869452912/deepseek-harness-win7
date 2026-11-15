from types import SimpleNamespace
import pytest
from scripts.rc022_tree_membership_probe import Agent,observe


@pytest.mark.asyncio
async def test_membership_authority_names_and_durable_ancestry():
    rows={(row['kind'],row['action']):row for row in await observe()}
    live=lambda action:rows['live',action]
    ancestry=lambda action:rows['ancestry',action]
    assert live('ordinary-fork')['root']=='ordinary'
    assert live('creator-gone')['root']=='root'
    for action in ('own-descriptor','origin','stale-caller','stale-root','stale-activation','external'):
        assert live(action)['error']['code']=='UNAUTHORIZED'
    assert live('named')['names']==dict(self='worker/nested',parent='worker')
    assert live('unnamed-parent')['names']==dict(self='child',parent='parent')
    assert live('name-known')['value']=='child'
    assert live('name-id')['value']=='historical-id'
    assert live('name-missing-path')['error']['code']=='AGENT_NAME_NOT_FOUND'
    assert ancestry('normal')['value']==dict(root='root',ancestors=['root','parent'],path='worker/nested')
    assert ancestry('normal')['trace']==['read:parent','dispose:parent','read:root','dispose:root']
    assert ancestry('unnamed')['value']['path'] is None
    assert ancestry('root-cold')['error']['code']=='CONTINUATION_UNAVAILABLE'
    assert ancestry('unavailable')['error']['code']=='NOT_RESUMABLE'
    for action in ('missing-edge','cycle','inherited-identity','no-identity','no-parent','foreign-root','delegated-root'):
        assert ancestry(action)['error']['code']=='UNAUTHORIZED'
    assert ancestry('abort')['trace']==[]


@pytest.mark.asyncio
async def test_actual_query_validates_catalog_edges_before_restoring_target():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.session.query_current import CurrentSessionQueryService
    from dsh.subagent.catalog import CATALOG
    from dsh.subagent.projections import IDENTITY
    from dsh.subagent.tree import SubagentTree
    from dsh.subagent.errors import SubagentError
    ctx=Context()
    store=CurrentSessionStore(ctx,4)
    projections=SessionProjectionRegistry(ctx,4)
    try:
        catalog=await projections.register(CATALOG)
        identity=await projections.register(IDENTITY)
        root=Agent('root');root.session=store.create('root')
        live={'root':root};ctx.set_service('agents',SimpleNamespace(get=live.get))
        query=CurrentSessionQueryService(ctx);ctx.set_service('sessionQuery',query)
        tree=SubagentTree(ctx,SimpleNamespace(identityOf=lambda session:identity.stateOf(session).get('identity'),
            catalogOf=lambda session:CATALOG['wire']['view'](catalog.stateOf(session))))
        parent=store.create('parent',dict(meta=dict(parentSession='root',origin='subagent')))
        child=store.create('child',dict(meta=dict(parentSession='parent',origin='subagent')))
        for session in (parent,child):
            session.append('subagent/descriptor',dict(version=3,mode='continuable',provider='fork',label=session.id))
        parent.append('subagent/catalog',dict(version=3,childId='child',childCreatedAt=1,mode='continuable',label='Child',name='nested'))
        source=await query.observeSession('child',{})
        try:
            with pytest.raises(SubagentError,match='absent from its creator catalog'):
                await tree.resolve_creation_ancestry(source,NEVER_ABORTED,root)
        finally:source.dispose()
        root.session.append('subagent/catalog',dict(version=3,childId='parent',childCreatedAt=1,mode='continuable',label='Parent',name='worker'))
        source=await query.observeSession('child',{})
        try:
            assert await tree.resolve_creation_ancestry(source,NEVER_ABORTED)==dict(root=root,ancestors=['root','parent'],path='worker/nested')
        finally:source.dispose()
        # Discovery and membership reads never enter the absent ancestors as Agents.
        assert set(live)=={'root'} and tree.resident=={}
        assert await tree.resolve_name(root,'worker/nested')=='child'
    finally:await ctx.fiber.dispose()
