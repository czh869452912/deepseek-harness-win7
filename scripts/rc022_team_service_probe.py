"""Pair the Team service against real v4 Agent/Session/subagent providers."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    def create(**extra):return dict(dict(op='create',subject=' Task ',description=' Details '),**extra)
    def update(identity,revision,action,**extra):return dict(op='update',taskId='task-'+str(identity),expectedRevision=revision,action=action,**extra)
    return [
        dict(name='workflow',commands=[dict(op='enable',value=True),create(),create(blockedBy=['task-1']),
            update(2,1,'claim',caller='b'),update(1,1,'claim',caller='a'),update(1,2,'claim',caller='b'),update(1,2,'complete',caller='a'),
            update(2,1,'claim',caller='b'),update(2,2,'edit',caller='a',subject='unauthorized'),update(2,2,'reassign',owner='root'),
            update(2,3,'release'),update(2,4,'edit',subject='Edited',writeScopes=['./src/','src','src\\a']),
            update(2,5,'delete'),update(1,3,'delete'),dict(op='get',taskId='task-2')]),
        dict(name='dependencies',commands=[dict(op='enable',value=True),create(),create(blockedBy=['task-1']),
            update(1,1,'set_dependencies',blockedBy=['task-2']),update(1,1,'delete'),update(2,1,'set_dependencies',blockedBy=[]),
            update(1,1,'delete'),create(blockedBy=['task-1']),create(writeScopes=['../bad']),create(subject=' ')]),
        dict(name='concurrent-claims',commands=[dict(op='enable',value=True),create(),dict(op='concurrent',requests=[update(1,1,'claim',caller='a'),update(1,1,'claim',caller='b')]),
            update(1,2,'release'),dict(op='cold',identity='b'),update(1,3,'reassign',owner='b'),update(1,4,'complete'),update(1,5,'reopen'),
            update(1,6,'reassign',owner='unknown'),update(1,6,'edit'),update(1,6,'set_dependencies')]),
        dict(name='disabled',commands=[create(),dict(op='enable',value=True),create(),dict(op='enable',value=False),dict(op='get',taskId='task-1'),
            dict(op='enable',value=True),dict(op='reload'),dict(op='get',taskId='task-1')]),
        dict(name='task-limit',config=dict(maxTasks=1),commands=[dict(op='enable',value=True),create(),create(),update(1,1,'delete'),create()]),
        dict(name='flush-false',commands=[dict(op='enable',value=True),dict(op='flush',value='false'),create(),dict(op='get',taskId='task-1'),dict(op='flush',value='real'),update(1,1,'edit',description='retained')]),
        dict(name='flush-error',commands=[dict(op='enable',value=True),dict(op='flush',value='error'),create(),dict(op='get',taskId='task-1'),dict(op='flush',value='real'),update(1,1,'claim')]),
        dict(name='mode-retry',commands=[dict(op='flush',value='error'),dict(op='enable',value=True),dict(op='flush',value='real'),dict(op='enable',value=True),create()]),
        dict(name='default-enabled',config=dict(defaultEnabled=True),commands=[create(),dict(op='enable',value=False,caller='a')]),
        dict(name='removed-config',config=dict(maxMembers=2),commands=[]),
        dict(name='unsafe-config',config=dict(maxTasks=9007199254740992),commands=[]),
        dict(name='stale-queue',commands=[dict(op='enable',value=True),dict(op='queue-race',race='stale')]),
        dict(name='disabled-queue',commands=[dict(op='enable',value=True),dict(op='queue-race',race='disabled')]),
    ]


def failure(error):
    return dict(error=getattr(error,'code',None),message=getattr(error,'message',str(error)))


async def observe(workspace):
    from dsh.team.service import TeamPlugin
    from scripts.rc022_subagent_fixture import setup
    rows=[]
    for case in cases():
        fixture=await setup(workspace/case['name']);ctx=fixture.ctx;signal=fixture.signal
        row=dict(name=case['name'],results=[]);owner=None;original_flush=ctx.sessions.flush
        try:
            owner=await ctx.plugin(TeamPlugin,case.get('config',{}))
            team=ctx.get('agentTeams')
            parent=(await ctx.agentLoop.create('root',dict(provider='script',model='model'))).agent
            async def guard(payload,next):return dict(kind='reject') if payload['agent'] is parent else await next()
            ctx.on('agent/pre-step',guard)
            actors=dict(root=parent);receipts={}
            for identity in ('a','b'):
                receipt=await fixture.service.startActivation(dict(provider='spawn',parent=parent,childId=identity,name=identity,label='Task',
                    prompt=[dict(type='text',text='TASK:'+identity)],signal=signal,delivery='caller'))
                actors[identity]=ctx.agents.get(identity);receipts[identity]=receipt
            flush_mode='real'
            async def flush(session=None):
                if flush_mode=='false':return False
                if flush_mode=='error':raise RuntimeError('disk unavailable')
                return await original_flush(session)
            ctx.sessions.flush=flush
            async def execute(command):
                nonlocal owner,team,flush_mode
                try:
                    caller=actors[command.get('caller','root')];op=command['op']
                    request={key:value for key,value in command.items() if key not in ('op','caller')}
                    if op=='enable':await team.setEnabled(caller,command['value'],signal);return dict(enabled=team.isEnabled(parent))
                    if op=='create':return await team.createTask(caller,request,signal)
                    if op=='update':return await team.updateTask(caller,request,signal)
                    if op=='get':return team.getTask(caller,command['taskId'])
                    if op=='cold':await receipts[command['identity']]['dispose']();return dict(cold=command['identity'])
                    if op=='flush':flush_mode=command['value'];return dict(flush=flush_mode)
                    if op=='concurrent':return await asyncio.gather(*(execute(request) for request in command['requests']))
                    if op=='reload':
                        await owner.dispose();owner=await ctx.plugin(TeamPlugin,case.get('config',{}));team=ctx.get('agentTeams')
                        return dict(reloaded=True)
                    if op=='queue-race':
                        entered,release=asyncio.Event(),asyncio.Event()
                        async def held(session=None):
                            if session is parent.session and not release.is_set():entered.set();await release.wait()
                            return await original_flush(session)
                        ctx.sessions.flush=held
                        first=asyncio.create_task(execute(dict(op='create',subject='first',description='first')))
                        await asyncio.wait_for(entered.wait(),3)
                        second=asyncio.create_task(execute(dict(op='create',subject='second',description='second',caller='a')))
                        await asyncio.sleep(0)
                        mode=None
                        if command['race']=='stale':await receipts['a']['dispose']()
                        else:
                            mode=asyncio.create_task(execute(dict(op='enable',value=False)))
                            await asyncio.sleep(0)
                        release.set()
                        results=await asyncio.gather(first,second)
                        if mode is not None:await mode
                        ctx.sessions.flush=flush
                        return results
                    raise RuntimeError('unknown probe operation')
                except Exception as error:return failure(error)
            for command in case['commands']:row['results'].append(await execute(command))
            row['projection']=ctx.sessionProjections.snapshot(parent.session)['values']['agentTeam']
            row['taskEvents']=sum(event['type']=='team/task' for event in parent.session.events)
            row['modeEvents']=sum(event['type']=='team/mode' for event in parent.session.events)
            row['tails']=len(team.journal.tails)
        except Exception as error:row.update(failure(error))
        finally:
            ctx.sessions.flush=original_flush
            if owner is not None:await owner.dispose()
            row['released']=ctx.get('agentTeams') is None
            await ctx.fiber.dispose()
        rows.append(row)
    return json.loads(json.dumps(rows))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    workspace=output/'workspace.json';workspace.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8')
    inputs=output/'cases.json';inputs.write_text(json.dumps(cases()),encoding='utf-8')
    return [workspace,inputs]


if __name__=='__main__':
    probe.native=lambda:observe(WORKSPACE/'native')
    probe.main('rc022_team_service.mts','Actual Team/subagent/factory/persistence service workflows, revision-CAS and queued stale/mode races, cold assignees, mode retry, task limits, failed flush visible state, reload and configuration retirement.',
        [Path(__file__).resolve(),ROOT/'scripts/rc022_subagent_fixture.py',ROOT/'scripts/oracles/rc022_subagent_fixture.mts',
         *[ROOT/'dsh/team'/name for name in ('service.py','journal.py','task_board.py')]],prepare=prepare)
