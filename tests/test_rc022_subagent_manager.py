import pytest
from scripts.rc022_subagent_manager_probe import observe


@pytest.mark.asyncio
async def test_actual_v4_creation_cold_resume_and_rollback(tmp_path):
    rows={row['action']:row for row in await observe(tmp_path)}
    for row in rows.values():
        assert not row['resident'] and not row['childLive']
        assert row['reservations']==0 and row['slots']==0
    for action in ('fresh','fork','resume'):
        assert rows[action]['result']==dict(output=[dict(type='text',text='answer')],stopReason='completed')
        assert rows[action]['catalog']==[dict(id='child',name='worker',mode='continuable',label='Task')]
        assert all(item['published'] and item['own'] for item in rows[action]['captured'])
    assert rows['fork']['captured'][0]['inherited']==2
    assert len(rows['resume']['descriptors'])==1
    assert rows['resume']['turns']==['completed','completed']
    assert len(rows['resume']['edges'])==4 and rows['resume']['resolved']=='child'
    for action in ('prepare-failure','directory-failure','capacity','catalog-failure'):
        assert 'error' in rows[action] and 'receipt' not in rows[action]
        assert rows[action]['catalog']==[]
    assert rows['catalog-failure']['edges'][-1]['stopReason']=='aborted'
    assert rows['capacity']['error']=='ACTIVATION_LIMIT_REACHED'
    assert rows['external']['catalog']==[dict(id='external',name='worker',mode='external',label='Task')]
    assert rows['external']['result']['output']==[dict(type='text',text='remote')]


@pytest.mark.asyncio
async def test_actual_sandbox_provider_exposes_delegation_snapshot_interface():
    from types import SimpleNamespace
    from dsh.cordis import Context
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.sandbox.sandbox_policy import SandboxPolicyService
    from dsh.subagent.child_agent import capture_delegated_policy_overrides
    ctx=Context()
    try:
        store=CurrentSessionStore(ctx,4)
        policy=SandboxPolicyService(ctx,dict(mode='danger-full-access'))
        session=store.create('parent')
        parent=SimpleNamespace(ctx=ctx,session=session)
        assert capture_delegated_policy_overrides(parent)=={}
        session.append('sandbox/mode',dict(mode='workspace-write',source='delegation'))
        assert policy.overrideOf(session)=='workspace-write'
        assert capture_delegated_policy_overrides(parent)==dict(sandboxMode='workspace-write')
    finally:await ctx.fiber.dispose()
