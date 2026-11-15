import asyncio
import pytest
from scripts.rc022_delegation_selection_probe import observe


@pytest.mark.asyncio
async def test_model_preset_authority_and_effort_override_contracts():
    rows=await observe()
    models=[row for row in rows if row['kind']=='model']
    assert models[0]['same'] and models[0]['value'] is None
    assert models[2]['cleared'] and models[2]['value']==dict(provider='p',model='m')
    assert 'not allowed' in models[6]['error']
    assert models[7]['value']==dict(provider='q',model='other') and models[7]['cleared']
    checkpoints=[row['accepted'] for row in rows if row['kind']=='checkpoint']
    assert checkpoints==[True,False,True,True,False,False]
    route_rows=[row for row in rows if row['kind']=='routes']
    assert 'repeats route' in route_rows[4]['error']
    assert route_rows[-1]['accepted']


@pytest.mark.asyncio
async def test_same_route_explicit_selection_uses_model_default_in_real_child(tmp_path):
    from dsh.core.session.json import UNDEFINED
    from dsh.subagent.selection import requested_options
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    fixture=await setup(tmp_path);ctx=fixture.ctx
    try:
        ctx.llm.registerAdapter(['reasoning'],ScriptAdapter(dict(script=[response('answer')],reasoning=dict(
            efforts=[dict(id='low',name='Low'),dict(id='high',name='High')],defaultEffort='low'))))
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='reasoning',model='m',reasoningEffort='high')))).agent
        selected=requested_options(UNDEFINED,dict(provider='reasoning',model='m'),True,UNDEFINED,parent.options.to_dict())
        assert selected['reasoningEffort'] is UNDEFINED
        published=[]
        ctx.on('subagent/start',lambda info:published.append(ctx.agents.get(info['id']).options.to_dict()))
        receipt=await fixture.service.startActivation(dict(provider='spawn',parent=parent,childId='child',name='worker',label='Task',
            prompt=[dict(type='text',text='task')],signal=fixture.signal,delivery='caller',agentOptions=selected))
        assert (await asyncio.wait_for(asyncio.shield(receipt['result']),3))['stopReason']=='completed'
        assert 'reasoningEffort' not in published[0]
        observation=await ctx.get('sessionQuery').observeSession('child',{})
        try:
            descriptor=next(event['data'] for event in observation.events if event['type']=='subagent/descriptor')
            request=next(event['data']['header'] for event in observation.events if event['type']=='request/header')
            assert 'agentReasoningEffort' not in descriptor
            assert request['config']['reasoningEffort']=='low'
            assert parent.options.reasoningEffort=='high'
        finally:observation.dispose()
    finally:await ctx.fiber.dispose()
