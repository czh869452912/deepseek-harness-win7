"""Pair target-only controls and real local/cold continuation delivery."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    payloads=[None,False,[],{},dict(childSessionId=''),dict(childSessionId=1),dict(childSessionId='child'),dict(childSessionId='child',delivery='queue'),dict(childSessionId='child',delivery='later')]
    return dict(validation=[dict(method=method,payload=payload) for method in ('subagent.prompt','subagent.interrupt') for payload in payloads],
        codes=['CANCELLED','MODEL_DOES_NOT_SUPPORT_IMAGES','NOT_RESUMABLE','UNAUTHORIZED','DRAINING','ACTIVATION_CLOSING','ACTIVATION_LIMIT_REACHED','CONTINUATION_UNAVAILABLE','PERSISTENCE_UNAVAILABLE','INPUT_CLOSED','UNKNOWN'])


def failure(error):return dict(code=getattr(error,'code',None),message=str(error),details=getattr(error,'details',None))


async def observe(workspace):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.control import validate_control_request,reject_prompt
    from dsh.subagent.errors import SubagentError
    from dsh.attachment.error import AttachmentError
    fixture=await setup(workspace);ctx=fixture.ctx;service=fixture.service;signal=fixture.signal;rows=[]
    try:
        for case in cases()['validation']:
            try:validate_control_request(case['method'],case['payload']);row=dict(accepted=True)
            except Exception as error:row=failure(error)
            rows.append(dict(kind='validation',value=row))
        for code in cases()['codes']+['attachment','internal']:
            error=AttachmentError('image refused','TOO_MANY_IMAGES') if code=='attachment' else RuntimeError('private detail') if code=='internal' else SubagentError('private detail',code)
            try:reject_prompt(error,'child',signal)
            except Exception as rejected:rows.append(dict(kind='rejection',value=failure(rejected),cause=rejected.cause is error))
        parent=(await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))).agent
        receipt=await service.startActivation(dict(provider='spawn',parent=parent,childId='child',name='worker',label='Task',prompt=[dict(type='text',text='Task')],signal=signal,delivery='caller'))
        while ctx.agents.get('child').status!='running':await asyncio.sleep(.001)
        received=[]
        def inserted(payload):
            message=payload['message']
            if message['source'].get('rpcId'):
                received.append(dict(target=payload['agent'].id,source=message['source'],content=message['content']))
        ctx.on('agent/inbox/inserted',inserted)
        for delivery in ('queue','steer','cold'):
            if delivery=='cold':await receipt['dispose']()
            caller_service=ctx.extend(dict(invocation=dict(peer=dict(principal=dict(kind='owner') if delivery=='queue' else dict(kind='test-guest',guest='g1'))))).get('subagents')
            request=dict(requestId='rpc-'+delivery,childSessionId='child',delivery='steer' if delivery=='steer' else 'queue',content=[dict(type='text',text=delivery)],clientTimeZone='Asia/Shanghai')
            answer=await caller_service.prompt(request,signal)
            rows.append(dict(kind='delivery',name=delivery,accepted=bool(answer['messageId']),message=received[-1]))
        for request in [dict(childSessionId='',delivery='queue'),dict(childSessionId='child',delivery='later'),dict(childSessionId='child',delivery='queue',clientTimeZone='bad-zone')]:
            try:await service.prompt(dict(requestId='invalid',content=[dict(type='text',text='invalid')],**request),signal)
            except Exception as error:rows.append(dict(kind='invalid',value=failure(error)))
        for child in ('child','absent',''):
            try:rows.append(dict(kind='interrupt',target=child,value=service.interruptByUser(child)))
            except Exception as error:rows.append(dict(kind='interrupt',target=child,value=failure(error)))
    finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'/'native'
    workspace=output/'workspace.json';workspace.write_text(json.dumps(str(output/'files')),encoding='utf-8')
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [workspace,path]


if __name__=='__main__':
    async def native():return await observe(WORKSPACE)
    probe.native=native
    probe.main('rc022_subagent_control.mts','Target-only control validation, exact failure details/cause, real Queue/Steer/cold delivery, owner omission/non-owner durable attribution, time zone and no-op interrupt. Gateway resource authorization not yet activated.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/control.py',ROOT/'dsh/typert/principal.py',ROOT/'dsh/typert/remote.py',ROOT/'dsh/subagent/service.py'],prepare=prepare)
