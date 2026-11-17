"""Current runtime delivery transactions against the actual fixed Source class."""
import asyncio
import copy
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_schedule_update_probe import NOW
from scripts.rc022_schedule_storage_probe import STAMP,receipt


def cases():
    return ['one','every','batch','partialCommit','flushFalse','flushReject','activateReject','rollbackActivate','rollbackFlush',
        'manual','manualPaused','manualMissing','manualArchived','newOnce','newEach','newRetry','newCreateReject','newArchived',
        'recoveryIdle','recoveryRunning','recoveryArchived','floorOccurrence','floorAck','future','farFuture','newFloor']


def normalize(value):
    sessions={};messages={}
    def visit(value):
        if isinstance(value,str):
            if re.fullmatch(r'session-[0-9a-f-]{36}',value):return sessions.setdefault(value,'reserved-'+str(len(sessions)+1))
            if re.fullmatch(r'[0-9a-f-]{36}',value):return messages.setdefault(value,'message-'+str(len(messages)+1))
            return value
        if isinstance(value,list):return [visit(item) for item in value]
        if isinstance(value,dict):return {key:visit(item) for key,item in value.items()}
        return value
    return visit(json.loads(json.dumps(value)))


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.schedule import runtime_current as runtime
    from dsh.schedule.storage_current import parse_schedule_task
    from dsh.typert.remote import RemoteError
    rows=[]
    for name in cases():
        clock=[NOW];trace=[];warnings=[];changed=[];agents={};handles=[];state=[];flushes=[0];titles={};all_agents=[]
        class Agent:
            def __init__(self,id):
                self.id=id;self.session=SimpleNamespace(id=id);self.status='idle';self.inbox=SimpleNamespace(nextTurn=[],nextStep=[])
                self.idle=asyncio.get_running_loop().create_future();all_agents.append(self)
                def remove(id):self.inbox.nextTurn[:]=[message for message in self.inbox.nextTurn if message['id']!=id]
                self.inbox.remove=remove
            def followup(self,message):trace.append(['followup',self.id,message]);self.inbox.nextTurn.append(message);self.status='running'
            def whenIdle(self):return self.idle
        agents['s']=Agent('s')
        async def activate(id):
            trace.append(['activate',id])
            if name=='activateReject':raise RuntimeError('activation refused')
            if name=='rollbackActivate':clock[0]=NOW-60000
            if id not in agents:raise RemoteError('session/not-found','not found',{})
            return agents[id]
        async def create(request):
            trace.append(['create',request])
            if name=='newCreateReject':raise RuntimeError('creation refused')
            agents[request['sessionId']]=Agent(request['sessionId'])
        async def flush(session):
            trace.append(['flush',session.id]);flushes[0]+=1
            if name=='rollbackFlush':clock[0]=NOW-120000
            if name=='flushReject':raise RuntimeError('flush refused')
            return not(name=='flushFalse' or name=='newRetry' and flushes[0]==1)
        class Handle:
            def __init__(self,delay):self.delay=round(delay*1000);self.cancelled=False
            def cancel(self):self.cancelled=True
        def later(delay,callback,*args,**kwargs):
            handle=Handle(delay);handles.append(handle);return handle
        class Titles:
            def get(self,session):return titles.get(session.id)
            def rename(self,session,title):titles[session.id]=title;trace.append(['title',session.id,title])
        services=dict(agents=SimpleNamespace(withoutInitiator=lambda operation:operation()),sessions=SimpleNamespace(flush=flush),
            sessionController=SimpleNamespace(create=create),sessionTitle=Titles(),workspaceRegistry=SimpleNamespace(archivedSessionIds=['s'] if name in ('manualArchived','recoveryArchived') else ['reserved'] if name=='newArchived' else []))
        class Context:
            logger=SimpleNamespace(warn=lambda message:warnings.append(message))
            def get(self,key):return services.get(key)
            def waterfall(self,event,id,next_fn):return next_fn()
        record=dict(id='a',kind='every' if name in ('every','batch','partialCommit','floorOccurrence','floorAck','newFloor') else 'after',title='Title',prompt='prompt',scheduledAt=runtime.iso(NOW-60000))
        record['everySeconds' if record['kind']=='every' else 'afterSeconds']=60
        if name in ('future','farFuture'):record['scheduledAt']=runtime.iso(NOW+(60000 if name=='future' else runtime.MAX_TIMER_DELAY_MS+60000))
        target=dict(kind='new_once',sessionId='reserved',create={}) if name in ('newOnce','newArchived') else dict(kind='new',create={}) if name in ('newEach','newRetry','newCreateReject','newFloor') else dict(kind='session',sessionId='s')
        raw=dict(record=record,target=target,deliveryHistory=dict(records=[],earlierRecordsUnavailable=False),status='paused' if name=='manualPaused' else 'active')
        if name.startswith('recovery') or name in ('floorOccurrence','floorAck','newFloor'):
            ack=dict(receipt(),targetSessionId='s',scheduledAt=runtime.iso(NOW-120000),deliveredAt=runtime.iso(NOW-1000))
            if name in ('floorAck','newFloor'):ack['scheduledAt']=runtime.iso(NOW-60000)
            raw.update(lastDelivery=ack,updatedAt=runtime.iso(NOW+60000),deliveryHistory=dict(records=[ack],earlierRecordsUnavailable=True))
            if name.startswith('recovery'):
                agents['s'].inbox.nextTurn=[dict(id=ack['messageId'],role='user',content=[dict(type='text',text='saved')],source=dict(kind='schedule'))]
                if name=='recoveryRunning':agents['s'].status='running'
        state.append(parse_schedule_task(raw))
        if name in ('batch','partialCommit'):state.append(parse_schedule_task(dict(raw,record=dict(record,id='b',prompt='second'))))
        async def commit(task):
            trace.append(['commit',task])
            if name=='partialCommit' and task['record']['id']=='b':raise RuntimeError('write refused')
            index=next(index for index,current in enumerate(state) if current['record']['id']==task['record']['id']);state[index]=task
        limits=dict(retention=dict(days=30,records=200),newSessionIntervalMs=3600000)
        timer=runtime.CurrentScheduleRuntime(Context(),lambda:state,lambda operation:operation(),commit,lambda:changed.append(True),limits,activate)
        with patch.object(runtime,'now_ms',lambda:clock[0]),patch.object(asyncio.get_running_loop(),'call_later',later):
            result=None
            try:
                if name.startswith('manual'):
                    result=await timer.runNow('missing' if name=='manualMissing' else 'a')
                    if name in ('manual','manualPaused'):result=[result,await timer.runNow('a')]
                else:
                    await timer.drive()
                    if name=='newRetry':await timer.drive()
                outcome=dict(value=result)
            except Exception as error:outcome=dict(error=dict(code=getattr(error,'code',None),message=str(error)))
            row=dict(case=name,outcome=outcome,tasks=state,trace=copy.deepcopy(trace),executing=sorted(timer.executing),warnings=len(warnings),changed=len(changed),
                timer=None if timer.timer is None else timer.timer.delay)
            await timer.dispose()
            for agent in all_agents:
                if not agent.idle.done():agent.idle.set_result(None)
            await asyncio.sleep(0);await asyncio.sleep(0)
        rows.append(normalize(row))
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_runtime.mts',prepare=prepare,
        scope='Actual current runtime over controlled clocks/Agents: one-shot and recurring batch receipts, partial commits, flush refusal, rollback, execution recovery/floors, manual execution, reserved Session creation/retry and timer clamp. Generated identities normalized bijectively.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/schedule/runtime_current.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/schedule/schedule/src/runtime.ts'])
