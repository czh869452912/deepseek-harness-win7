"""Creation-time selection authorization over real candidate Agent/Session services."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    route=[dict(provider='alpha',model='fast-model')]
    return [
        dict(name='sampling',commands=[dict(op='create',id='off'),dict(op='settings',enabled=True,allowedModels=route),
            dict(op='create',id='on'),dict(op='settings',enabled=False),dict(op='read',id='on'),dict(op='read',id='off'),dict(op='create',id='off-again')]),
        dict(name='inherit',config=dict(enabled=True,allowedModels=route),commands=[dict(op='create',id='parent'),dict(op='settings',enabled=False),
            dict(op='create',id='child',parent='parent'),dict(op='create',id='orphan',parent='absent'),dict(op='create',id='seeded',seed='parent')]),
        dict(name='parent-disabled',commands=[dict(op='create',id='parent'),dict(op='settings',enabled=True,allowedModels=route),
            dict(op='create',id='child',parent='parent'),dict(op='create',id='seeded',seed='parent')]),
        dict(name='saved-policy',config=dict(enabled=True,allowedModels=route),commands=[dict(op='create',id='root',policy=[dict(provider='saved',model='route')]),
            dict(op='settings',enabled=False),dict(op='resume',id='root')]),
        dict(name='resume-unselected',commands=[dict(op='create',id='root'),dict(op='settings',enabled=True,allowedModels=route),dict(op='resume',id='root')]),
        dict(name='duplicate',config=dict(allowedModels=route+route),commands=[dict(op='create',id='invalid'),dict(op='settings',allowedModels=route),dict(op='create',id='valid')]),
        dict(name='empty',config=dict(enabled=True),commands=[dict(op='create',id='invalid'),dict(op='settings',enabled=False),dict(op='create',id='valid')]),
        dict(name='unload',config=dict(enabled=True,allowedModels=route),commands=[dict(op='create',id='before'),dict(op='unload'),dict(op='create',id='after')]),
    ]


async def observe(workspace):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.selection_settings import SubagentModelSelectionConfig
    from dsh.subagent.selection import POLICY,read_policy
    from dsh.core.session.json import UNDEFINED
    from dsh.cordis.volatile import create_volatile,WRITE
    rows=[]
    for case in cases():
        fixture=await setup(workspace/case['name']);ctx=fixture.ctx;row=dict(name=case['name'],results=[]);agents={};handles={}
        try:
            owner=await ctx.plugin(SubagentModelSelectionConfig,case.get('config',{}))
            refs=owner._effective_config
            policy=await ctx.sessionProjections.register(POLICY)
            def snapshot(agent):
                value=read_policy(policy,agent.session)
                return dict(policy=None if value is UNDEFINED else value,
                    policies=sum(event['type']=='subagent/model-selection-policy' for event in agent.session.snapshotEvents()))
            for command in case['commands']:
                try:
                    op=command['op'];identity=command.get('id')
                    if op=='settings':
                        for key in refs:
                            if key in command:getattr(refs[key],WRITE)(create_volatile(command[key]).get())
                        result=dict(updated=True)
                    elif op=='unload':
                        await owner.dispose();result=dict(released=ctx.get('subagentModelSelection') is None)
                    elif op=='read':result=snapshot(agents[identity])
                    else:
                        request=dict(sessionId=identity,agentOptions=dict(provider='script',model='model'))
                        if op=='resume':
                            agents[identity].session.append('session/title',dict(title='Saved',messageSeqs=[],source=dict(kind='user')))
                            await ctx.sessions.flush(agents[identity].session)
                            await handles[identity].dispose()
                            handle=await ctx.agents.resume(dict(resumeSessionId=identity))
                        else:
                            if 'parent' in command:request['meta']=dict(parentSession=command['parent'],origin='subagent')
                            if 'seed' in command:request['seed']=agents[command['seed']].session.snapshotEvents()
                            if 'policy' in command:
                                async def before(agent_ctx,agent):agent.session.append('subagent/model-selection-policy',dict(allowedModels=command['policy']))
                                request['setup']=before
                            handle=await ctx.agents.create(request)
                        handles[identity]=handle;agents[identity]=handle.agent;result=snapshot(handle.agent)
                    row['results'].append(result)
                except Exception as error:row['results'].append(dict(error=str(error)))
            row['agents']=[agent.id for agent in ctx.agents.list()]
        finally:await ctx.fiber.dispose()
        rows.append(row)
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'/'native'
    workspace=output/'workspace.json';workspace.write_text(json.dumps(str(output/'files')),encoding='utf-8')
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [workspace,path]


if __name__=='__main__':
    async def native():return await observe(WORKSPACE)
    probe.native=native
    probe.main('rc022_selection_settings.mts','Creation-time policy sampling, volatile updates, exact parent inheritance, missing parent, seeded sessions, saved policy and cold resume, invalid preference rollback and reversible unload.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/selection_settings.py',ROOT/'dsh/subagent/selection.py'],prepare=prepare)
