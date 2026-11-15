"""Current job ownership/output/lifecycle against real Session and Agent services."""
import asyncio
import json
from pathlib import Path
import re
from types import SimpleNamespace as NS
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.jobs.current import CurrentLocalJobRegistry
    fixture=await setup(WORKSPACE/'native',script=[]);ctx=fixture.ctx
    owner=await ctx.plugin(CurrentLocalJobRegistry,dict(retainBytes=12,settledRetainBytes=4,pumpPollMs=10000,maxConcurrentJobsPerOwner=1));jobs=ctx.jobs;rows=[];events=[];producer={};handles=[]
    agent=(await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))).agent
    jobs.events.subscribe(dict(owners='all'),lambda event:events.append(event))
    def run(handle):
        handles.append(handle);handle.append('seed',dict(channel='meta'));handle.updateProgress('preparing')
        future=asyncio.get_running_loop().create_future();producer[handle.id]=future
        return dict(done=future,cancel=lambda reason:future.set_result(dict(status='killed',detail='stopped')) if not future.done() else None)
    def call(name,fn):
        try:rows.append(dict(name=name,value=fn()))
        except Exception as error:rows.append(dict(name=name,error=getattr(error,'message',str(error)),code=getattr(error,'code',None)))
    async def drain():
        for _ in range(6):await asyncio.sleep(0)
    try:
        call('no-controller',lambda:jobs.start(dict(kind='pwsh',label='test',owner='root',run=run)))
        jobs.attachController('test')
        call('unknown-owner',lambda:jobs.start(dict(kind='pwsh',label='test',owner='missing',run=run)))
        identity=jobs.start(dict(kind='pwsh',label='test',owner='root',toolCall=dict(callId='call',toolName='pwsh'),run=run))
        call('initial',lambda:jobs.get(identity,'root'));call('foreign',lambda:jobs.get(identity,'other'))
        call('limit',lambda:jobs.start(dict(kind='pwsh',label='second',owner='root',run=run)))
        handle=handles[-1];handle.append('你好',dict(channel='stdout'));handle.append('tail',dict(channel='stderr'));handle.updateProgress('working')
        call('ui-read',lambda:jobs.readAt(identity,0,'root'));call('model-read',lambda:jobs.read(identity,'root'));call('second-read',lambda:jobs.read(identity,'root'))
        handle.append('final',dict(channel='stdout'));wait=asyncio.create_task(jobs.wait(identity,10000,'root'));await asyncio.sleep(0)
        producer[identity].set_result(dict(status='completed',detail='exit code: 0',result=dict(summary='done')));await wait;await drain()
        call('terminal-ui',lambda:jobs.readAt(identity,0,'root'));call('terminal-model',lambda:jobs.read(identity,'root'));call('result-once',lambda:jobs.read(identity,'root'))
        handle.append('ignored');handle.updateProgress('ignored');call('terminal-kill',lambda:jobs.kill(identity,'root','late'))
        jobs.remove(identity,'root');call('missing',lambda:jobs.get(identity,'root'))
        rows.append(dict(name='events',events=events))
        rows.append(dict(name='durable',events=[dict(type=event['type'],data=event['data']) for event in agent.session.snapshotEvents() if event['type'].startswith('job/')]))
        await edges(ctx,jobs,rows,drain)
        return normalize(json.loads(json.dumps(rows)))
    finally:
        for future in producer.values():
            if not future.done():future.set_result(dict(status='killed'))
        await owner.dispose();await ctx.fiber.dispose()


async def edges(ctx,jobs,rows,drain):
    from dsh.core.abort import AbortController
    class Error(Exception):pass
    async def call(name,operation):
        try:rows.append(dict(name=name,value=await operation))
        except Exception as error:rows.append(dict(name=name,error=str(error),errorName=getattr(error,'name','Error')))
    future=asyncio.get_running_loop().create_future();attempts=[]
    def cancel(reason):
        attempts.append(reason)
        if len(attempts)==1:raise Error('retry me')
        future.set_result(dict(status='killed',detail='signal: SIGTERM'))
    identity=jobs.start(dict(kind='pwsh',label='retry',run=lambda _:dict(done=future,cancel=cancel)))
    try:jobs.kill(identity,None,'first')
    except Error as error:rows.append(dict(name='cancel-throw',error=str(error),status=jobs.get(identity)['status']))
    controller=AbortController();waiting=asyncio.create_task(jobs.wait(identity,10000,None,controller.signal));await asyncio.sleep(0);controller.abort()
    await call('wait-abort',waiting);rows.append(dict(name='wait-timeout',status=(await jobs.wait(identity,1))['status']))
    jobs.kill(identity,None,'second');await jobs.wait(identity,10000);rows.append(dict(name='retry-killed',job=jobs.get(identity),attempts=attempts));jobs.remove(identity)
    future=asyncio.get_running_loop().create_future();identity=jobs.start(dict(kind='pwsh',label='reject',run=lambda _:dict(done=future,cancel=lambda _:None)))
    future.set_exception(Error('producer rejected'));await jobs.wait(identity,10000);rows.append(dict(name='rejected-producer',job=jobs.get(identity)));jobs.remove(identity)
    future=asyncio.get_running_loop().create_future();identity=jobs.start(dict(kind='pwsh',label='abort-on-settle',run=lambda _:dict(done=future,cancel=lambda _:None)))
    controller=AbortController();seen=[]
    detach=jobs.events.subscribe(dict(owners='all'),lambda event:(seen.append(event['awaited']),controller.abort()) if event['type']=='settled' else None)
    waiting=asyncio.create_task(jobs.wait(identity,10000,None,controller.signal));await asyncio.sleep(0);future.set_result(dict(status='completed'));await call('settle-wins-abort',waiting);detach();jobs.remove(identity)
    rows.append(dict(name='settle-awaited',value=seen))
    future=asyncio.get_running_loop().create_future()
    def throwing(_):raise Error('cannot cancel')
    identity=jobs.start(dict(kind='pwsh',label='orphan',run=lambda _:dict(done=future,cancel=throwing)))
    observed=[];detach=jobs.events.subscribe(dict(owners='all'),lambda event:observed.append(event) if event['type'] in ('settled','removed') else None)
    await jobs.dispose_all();future.set_result(dict(status='completed',detail='too late'));await drain();detach()
    rows.append(dict(name='teardown-first-wins',events=observed,jobs=jobs.list()))


def normalize(value):
    if isinstance(value,str):return re.sub(r'pwsh-[0-9a-f]{16}','<job>',value)
    if isinstance(value,list):return [normalize(item) for item in value]
    if isinstance(value,dict):return {key:0 if key in ('startedAt','finishedAt') else normalize(item) for key,item in value.items()}
    return value


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_job_registry.mts','Actual registry/Session/Agent integration for controller admission, owner identity, limit and access, staged producer writes, byte ring and non-consuming UI versus model cursor, one-shot result delivery, ordered durable lifecycle/stream events and terminal removal. Only minted job IDs and clock fields normalized.',[Path(__file__).resolve(),ROOT/'dsh/jobs/current.py',ROOT/'dsh/jobs/events.py',ROOT/'dsh/jobs/error.py'],prepare=prepare)
