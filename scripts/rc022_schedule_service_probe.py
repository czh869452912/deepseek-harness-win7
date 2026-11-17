"""Real Cordis/Domain/JSON management composition against current Source."""
import asyncio
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_schedule_update_probe import NOW

FILES=None

def normalize(value):
    identities={}
    def text(value):
        def replace(match):
            key=match.group(0);prefix=match.group(1) or 'message-'
            return identities.setdefault(key,prefix+str(1+sum(item.startswith(prefix) for item in identities.values())))
        return re.sub(r'(schedule-|session-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',replace,value)
    def visit(value):
        if isinstance(value,str):return text(value)
        if isinstance(value,list):return [visit(item) for item in value]
        if isinstance(value,dict):return {text(key):visit(item) for key,item in value.items()}
        return value
    return visit(json.loads(json.dumps(value)))

def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir()
    path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES))),encoding='utf-8');return [path]

async def observe(files=None):
    from dsh.cordis import Context
    from dsh.schedule import service_current as current,runtime_current as runtime
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.domain_impl import DomainFacility
    ctx=Context();trace=[];changes=[];rows=[];agents={};files=Path(files or FILES);files.mkdir(exist_ok=True,parents=True)
    for id,status,depth in [('actor','idle',0),('target','running',0),('editor','idle',0),('child','idle',1)]:
        def make(id,status,depth):return SimpleNamespace(id=id,status=status,options=dict(subagentDepth=depth),session=SimpleNamespace(id=id,header=SimpleNamespace(delegationDepth=depth)),inject=lambda message:trace.append(['inject',id,message]))
        agents[id]=make(id,status,depth)
    async def stat(id,options=None):
        trace.append(['stat',id])
        if id=='inspect-error':raise RuntimeError('stat refused')
        if id=='missing' or id.startswith('session-'):return None
        return dict(header=dict(delegationDepth=1 if id=='stored-child' else 0))
    async def flush(session):trace.append(['flush',session.id]);return True
    async def resolve(id):trace.append(['activate',id]);raise RuntimeError('unexpected activation')
    async def create(request):trace.append(['create-session',request]);raise RuntimeError('unexpected creation')
    ctx.provide('agents',SimpleNamespace(get=agents.get,withoutInitiator=lambda work:work()))
    ctx.provide('sessions',SimpleNamespace(flush=flush));ctx.provide('sessionPersistence',SimpleNamespace(stat=stat))
    ctx.provide('sessionController',SimpleNamespace(resolveAgent=resolve,create=create))
    ctx.provide('workspaceRegistry',SimpleNamespace(archivedSessionIds=['archived']))
    backend=JsonStorageBackend(str(files/'native'));ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda name:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
    ctx.on('schedule/changed',lambda:changes.append(True))
    async def stable(service):
        await asyncio.shield(service.chain);await asyncio.shield(service.notifications)
        if service.runtime.running is not None:await asyncio.shield(service.runtime.running)
        await asyncio.sleep(0)
    with patch.object(current,'now_ms',lambda:NOW),patch.object(runtime,'now_ms',lambda:NOW):
        fiber=ctx.plugin(current.CurrentScheduleService,config={});await fiber;service=getattr(ctx.get('schedule'),'cordis.original')
        async def step(label,operation):
            start=len(trace);before=len(changes)
            try:value=await operation();answer=dict(value=value)
            except Exception as error:answer=dict(error=dict(name=getattr(error,'name','Error'),code=getattr(error,'code',None),message=str(error),details=getattr(error,'details',None)))
            await stable(service)
            rows.append(dict(step=label,**answer,trace=trace[start:],changes=len(changes)-before))
            return answer.get('value')
        try:
            await stable(service)
            async def effective():return service.deliveryLimits()
            await step('limits',effective)
            request=dict(title=' First ',prompt=' Prompt ',timing=dict(kind='after',after_seconds=3600),target=dict(kind='session',sessionId='target'))
            first=await step('create',lambda:service.create(request,'actor'))
            id=first['id']
            await step('view',lambda:service.view(dict(id=id)))
            await step('catalog',service.catalog)
            await step('list',lambda:service.list({}))
            await step('list-inactive',lambda:service.list(dict(active=False)))
            await step('invalid-list',lambda:service.remoteList(dict(limit=0)))
            await step('history',lambda:service.remoteHistory(dict(id=id,limit=10)))
            await step('invalid-history',lambda:service.remoteHistory(dict(id=id,limit=101)))
            await step('missing-view',lambda:service.view(dict(id='missing')))
            await step('missing-run',lambda:service.run(dict(id='missing')))
            await step('pause',lambda:service.edit(dict(id=id,action='update',patch=dict(title='Updated',prompt='new prompt',active=False),expectedUpdatedAt=first['updatedAt']),'editor'))
            await step('conflict',lambda:service.remoteEdit(dict(id=id,action='update',patch=dict(title='stale'),expectedUpdatedAt=first['updatedAt'])))
            await step('empty-patch',lambda:service.remoteEdit(dict(id=id,action='update',patch={})))
            await step('retarget',lambda:service.edit(dict(id=id,action='update',patch=dict(target=dict(kind='new'),timing=dict(kind='every',every_seconds=300)))))
            await step('resume',lambda:service.edit(dict(id=id,action='update',patch=dict(active=True,timing=dict(kind='after',after_seconds=7200)))))
            await step('default-create',lambda:service.remoteCreate(dict(title='Default',prompt='default',timing=dict(kind='after',after_seconds=5400))))
            for target in ['missing','inspect-error','child','stored-child','archived']:
                await step('refuse-'+target,lambda target=target:service.remoteCreate(dict(request,target=dict(kind='session',sessionId=target))))
            domain=await service.get_domain();tasks=domain.table('tasks')
            ended_record={key:value for key,value in dict(first,id='ended').items() if key in ('id','kind','title','prompt','afterSeconds','scheduledAt')}
            ended=current.parse_schedule_task(dict(record=ended_record,target=dict(kind='session',sessionId='target'),status='ended'))
            await tasks.put('ended',ended)
            await step('delete-inactive',service.deleteInactive)
            await step('delete-inactive-empty',service.deleteInactive)
            def fail_observer():raise RuntimeError('observer refused')
            remove=ctx.on('schedule/changed',fail_observer)
            await step('observer-committed',lambda:service.edit(dict(id=id,action='update',patch=dict(title='Observed'))))
            remove()
            await step('delete',lambda:service.edit(dict(id=id,action='delete'),'actor'))
            await step('delete-missing',lambda:service.remoteEdit(dict(id=id,action='delete')))
            row=dict(step='final',tasks=[task for _,task in tasks.entries()],activationCalls=len([call for call in trace if call[0] in ('activate','create-session')]))
            rows.append(row)
        finally:
            await fiber.dispose();await facility.close_all();await backend.close();await ctx.fiber.dispose()
    return normalize(rows)

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_service.mts',prepare=prepare,
        scope='Actual Cordis service over routed DomainFacility and JSON storage: management/Remote errors, conflict revisions, target validation, idle/running notices, batch removal and post-commit observer containment. Generated identities normalized bijectively.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/schedule/service_current.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/schedule/schedule/src/index.ts'])
