import pytest
from scripts.rc022_selection_settings_probe import observe


@pytest.mark.asyncio
async def test_creation_time_policy_and_persisted_resume(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    sampled=rows['sampling']['results']
    assert sampled[0]==dict(policy=None,policies=0)
    assert sampled[2]==sampled[4] and sampled[2]['policies']==1
    assert sampled[-1]==sampled[0]
    inherited=rows['inherit']['results']
    assert inherited[0]==inherited[2]==inherited[4]
    assert inherited[3]==dict(policy=None,policies=0)
    assert rows['parent-disabled']['results'][2:]==[dict(policy=None,policies=0)]*2
    assert rows['saved-policy']['results'][0]==rows['saved-policy']['results'][-1]
    assert rows['resume-unselected']['results'][-1]==dict(policy=None,policies=0)
    assert rows['resume-unselected']['agents']==['root']
    assert rows['duplicate']['agents']==['valid'] and 'repeats route' in rows['duplicate']['results'][0]['error']
    assert rows['empty']['agents']==['valid'] and 'at least one' in rows['empty']['results'][0]['error']
    assert rows['unload']['results'][-2:]==[dict(released=True),dict(policy=None,policies=0)]


@pytest.mark.asyncio
async def test_actual_managed_child_captures_detached_policy_before_created_consumers(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.selection import POLICY,read_policy
    from dsh.subagent.selection_settings import SubagentModelSelectionConfig
    from dsh.cordis.volatile import WRITE
    fixture=await setup(tmp_path);ctx=fixture.ctx
    routes=[dict(provider='script',model='model')]
    try:
        owner=await ctx.plugin(SubagentModelSelectionConfig,dict(enabled=True,allowedModels=routes))
        policy=await ctx.sessionProjections.register(POLICY)
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        getattr(owner._effective_config['enabled'],WRITE)(False)
        seen=[]
        ctx.on('agent/created',lambda payload:seen.append(read_policy(policy,payload['agent'].session)))
        receipt=await fixture.service.startActivation(dict(provider='spawn',parent=parent,childId='child',name='worker',label='Task',
            prompt=[dict(type='text',text='task')],signal=fixture.signal,delivery='caller'))
        child=ctx.agents.get('child')
        assert seen==[routes] and read_policy(policy,child.session)==routes
        detached=read_policy(policy,child.session);detached[0]['model']='changed'
        assert read_policy(policy,parent.session)==read_policy(policy,child.session)==routes
        await receipt['dispose']()
    finally:await ctx.fiber.dispose()
