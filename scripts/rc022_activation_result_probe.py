"""Pair per-tree capacity, child locks, epoch output and settlement messages."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.subagent.activation import ActivationPool,ChildLock,capture_local_result,require_local_activation
    from dsh.subagent.messages import create_agent_message,create_settlement_message,with_result_delivery_guidance
    pool=ActivationPool();rows=[];releases=[pool.reserve(2),pool.reserve(2)]
    try:pool.reserve(2)
    except Exception as error:rows.append(dict(kind='capacity',code=error.code,message=str(error)))
    releases[0]();releases[0]();third=pool.reserve(2);releases[0]()
    try:pool.reserve(2)
    except Exception as error:rows.append(dict(kind='stale-release',code=error.code))
    third();releases[1]();pool.reserve(1)();rows.append(dict(kind='released',remaining=len(pool.slots)))
    locks=ChildLock();trace=[];entered=asyncio.Event();release=asyncio.Event()
    async def first():
        trace.append('first');entered.set();await release.wait();trace.append('failed');raise ValueError('first failure')
    async def second():trace.append('second');return 2
    one=locks.run('child',first);two=locks.run('child',second)
    await entered.wait()
    async def independent():trace.append('other');return 3
    other=await locks.run('other',independent);release.set()
    results=await asyncio.gather(one,two,return_exceptions=True)
    rows.append(dict(kind='locks',trace=trace,first=str(results[0]),second=results[1],other=other,remaining=len(locks.entries)))
    for reason in ('completed','aborted','interrupted','error','blocked','max-tokens','custom'):
        events=[dict(type='assistant/message',data=dict(message=dict(content=[dict(type='text',text='seed')]),stream=[])),
                dict(type='turn/start',data=dict(turn=1)),dict(type='step/start',data=dict(turn=1,step=1)),
                dict(type='assistant/message',data=dict(message=dict(content=[dict(type='text',text='answer')]),stream=[])),
                dict(type='assistant/message',data=dict(message=dict(content=[]),stream=[])),
                dict(type='turn/end',data=dict(turn=1,reason=dict(kind=reason)))]
        for structured in ('none','missing','null'):
            a=SimpleNamespace(handle=SimpleNamespace(agent=SimpleNamespace(session=SimpleNamespace(snapshotEvents=lambda cut:events[cut:]))),
                outputStart=1,failureAt=None,structured=None if structured=='none' else SimpleNamespace(captured=lambda:None if structured=='missing' else dict(value=None)))
            rows.append(dict(kind='capture',reason=reason,structured=structured,value=capture_local_result(a)))
        a.failureAt=0
        rows.append(dict(kind='failure',reason=reason,value=capture_local_result(a)))
    for reason in ('completed','aborted','max-tokens','refusal','error','custom'):
        for continuable in (True,False):
            for omit in (True,False):
                terminal=dict(stopReason=reason,output=[dict(type='text',text=''),dict(type='image',image='x'),dict(type='text',text='answer')],
                              structured=dict(result=None),diagnostic='detail')
                message=create_settlement_message('child','worker/nested',terminal,continuable,omit)
                message=json.loads(json.dumps({key:value for key,value in message.items() if key!='id'}));rows.append(dict(kind='notice',reason=reason,continuable=continuable,omit=omit,value=message))
    message=create_agent_message(SimpleNamespace(id='child'),'worker',[dict(type='text',text='hello')]);message=json.loads(json.dumps({key:value for key,value in message.items() if key!='id'}))
    rows.append(dict(kind='relay',value=message,guidance=with_result_delivery_guidance([])))
    message=create_settlement_message('child','\U0001f600'*80,dict(stopReason='completed',output=[]));message=json.loads(json.dumps({key:value for key,value in message.items() if key!='id'}))
    rows.append(dict(kind='bounded',value=message))
    try:require_local_activation(SimpleNamespace(kind='external',childId='external'))
    except Exception as error:rows.append(dict(kind='external',code=error.code,message=str(error)))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_activation_result.mts','Exact capacity slot identity, per-child failure-isolated locks, suffix-only output and structured result, named text-only settlement notices and durable attribution.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/activation.py',ROOT/'dsh/subagent/messages.py'])
