import gc
import weakref
import pytest
from scripts.rc022_team_projection_probe import observe,task


@pytest.mark.asyncio
async def test_durable_team_state_and_normalization_contracts():
    rows=await observe()
    projects={row['name']:row for row in rows if row['kind']=='project'}
    assert projects['task-enables']['view']['enabled']
    assert not projects['explicit-disabled']['view']['enabled']
    assert len(projects['retired-records']['state']['tasks'])==1
    sticky=projects['mode-after-failure']
    assert sticky['view']['enabled'] and len(sticky['view']['tasks'])==1
    assert sticky['state']['failure']=='team task "task-1" revision is not contiguous'
    assert projects['inherited-mode']['state']['enabled'] is False
    assert not projects['tombstone']['view']['tasks']
    assert projects['scopes-readiness']['steps'][1]['view']['tasks'][1]['writeScopeWarnings']==['write scopes overlap with task-1']
    assert projects['scopes-readiness']['view']['tasks'][1]['ready']
    assert projects['safe-id-exhausted']['state']['nextTaskNumber']==9007199254740991
    assert all('failure' in projects[name]['state'] for name in ('unsafe-id','owner-without-id','transitive-cycle','delete-blocker'))


@pytest.mark.asyncio
async def test_real_v4_registry_fork_and_checkpoint_restore():
    from dsh.cordis import Context
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.team.projection import TEAM
    ctx=Context()
    try:
        store=CurrentSessionStore(ctx,4);registry=SessionProjectionRegistry(ctx,4)
        handle=await registry.register(TEAM)
        parent=store.create('root')
        parent.append('team/mode',dict(enabled=True))
        parent.append('team/task',dict(version=2,teamId='root',task=task(ownerId='root',ownerName='lead')))
        seed=parent.snapshotEvents()
        child=store.create('fork',dict(seed=seed,inheritedEventCount=2,meta=dict(isSeeded=True,parentSession='root')))
        assert registry.snapshot(child)['values']['agentTeam']==dict(enabled=False,tasks=[])
        child.append('team/mode',dict(enabled=True))
        child.append('team/task',dict(version=2,teamId='fork',task=task()))
        checkpoint=registry.checkpoint(child)
        assert checkpoint['agentTeam']['ver']==7
        restored=registry.restore(checkpoint,[],child.seq,child.header,child.inheritedEventCount)
        assert restored['snapshot']['values']['agentTeam']==registry.snapshot(child)['values']['agentTeam']
        assert handle.stateOf(parent)['tasks'][0]['ownerName']=='lead'
    finally:await ctx.fiber.dispose()


def test_client_view_cache_does_not_retain_retired_task_collections():
    from dsh.team.projection import empty_team_state,team_projection_view,_views
    state=empty_team_state('temporary');key=id(state['tasks']);reference=weakref.ref(state['tasks'])
    assert team_projection_view(state) is team_projection_view(state)
    del state
    gc.collect()
    assert reference() is None and key not in _views
