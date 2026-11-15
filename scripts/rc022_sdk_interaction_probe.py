"""SDK question answer validation and exact live approval ownership."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.sdk.user_questions import SdkUserQuestionBridge
    from dsh.sdk.server import HarnessSdkJsonRpcServer
    from scripts.rc022_subagent_fixture import setup
    from dsh.core.abort import AbortController, abort_reason_error
    ctx=Context();rows=[];calls=[];notifications=[];response=[None];controller=AbortController();waiting=asyncio.Event()
    questions=[dict(id='q',question='Choose',options=[dict(label='A')])]
    async def request(method,params,signal):
        calls.append(dict(method=method,sessionId=params['sessionId'],questions=params.get('questions'),toolName=params.get('toolName'),callId=params.get('callId'),reason=params.get('reason')))
        if response[0]=='failure':raise RuntimeError('offline')
        if response[0]=='wait':
            waiting.set();await signal.wait_aborted();raise abort_reason_error(signal)
        return response[0]
    peer=NS(request=request,notify=lambda name,params:notifications.append(dict(name=name,sessionId=params['sessionId'])) if name=='user-question.cancelled' else None)
    bridge=SdkUserQuestionBridge(ctx,peer,lambda agent:agent.id=='owned')
    agent=NS(id='owned',session=NS(id='owned'))
    async def fallback():return dict(fallback=True)
    async def ask(name,value,request_agent=agent):
        response[0]=value
        request_value=dict(questions=questions)
        if request_agent is not None:request_value['agent']=request_agent
        try:result=dict(value=await ctx.waterfall('user-questions/request',request_value,fallback))
        except Exception as error:result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(name=name,result=result,calls=len(calls)))
    try:
        await ask('disabled',None);bridge.enabled=True
        await ask('unowned',None,NS(id='other',session=NS(id='other')))
        await ask('no-agent',None,None)
        values=[('answer',dict(answers=[dict(id='q',selected=['A'],custom='text',extra=True)])),('outer-extra',dict(answers=[dict(id='q',selected=[])],extra=True)),('dismissed',dict(cancelled=True)),('cancel-false',dict(cancelled=False)),('cancel-extra',dict(cancelled=True,extra=1)),('null',None),('missing',{}),('empty',dict(answers=[])),('wrong-id',dict(answers=[dict(id='x',selected=[])])),('duplicate',dict(answers=[dict(id='q',selected=[])]*2)),('selected-type',dict(answers=[dict(id='q',selected='A')])),('selected-value',dict(answers=[dict(id='q',selected=[1])])),('custom-type',dict(answers=[dict(id='q',selected=[],custom=1)])),('provider-failure','failure')]
        for name,value in values:await ask(name,value)
        response[0]='wait';pending=asyncio.create_task(ctx.waterfall('user-questions/request',dict(agent=agent,questions=questions,signal=controller.signal),fallback));await waiting.wait();controller.abort(RuntimeError('request stopped'))
        try:await pending
        except Exception as error:rows.append(dict(name='request-abort',error=getattr(error,'message',str(error)),code=getattr(error,'code',None),notifications=list(notifications)))
        waiting.clear();pending=asyncio.create_task(ctx.waterfall('user-questions/request',dict(agent=agent,questions=questions),fallback));await waiting.wait();bridge.close()
        try:await pending
        except Exception as error:rows.append(dict(name='question-shutdown',error=getattr(error,'message',str(error)),code=getattr(error,'code',None),notifications=list(notifications)))
    finally:bridge.close();await ctx.fiber.dispose()
    fixture=await setup(Path(WORKSPACE)/'native');ctx=fixture.ctx
    server=HarnessSdkJsonRpcServer(ctx,peer)
    try:
        await server.initialize(dict(cwd=str(WORKSPACE),provider='script',model='model'))
        handle=await server.get_or_create('root');root=handle.agent
        async def decision(name,value,selected=root):
            response[0]=value
            async def rejected():return 'fallback'
            try:result=dict(value=await ctx.waterfall('approval/request',dict(agent=selected,toolName='terminal',callId='call',reason='test'),rejected))
            except Exception as error:result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
            rows.append(dict(name=name,result=result,calls=len(calls)))
        await decision('approval-disabled',dict(outcome='allowed-once'));server.approval_requests=True
        for name,value in [('allow',dict(outcome='allowed-once',extra=1)),('reject',dict(outcome='rejected')),('cancel',dict(outcome='cancelled')),('unavailable',dict(outcome='unavailable')),('approval-null',None),('approval-missing',{})]:await decision(name,value)
        outsider=await ctx.agents.create(dict(sessionId='outsider',agentOptions=dict(provider='script',model='model')));await decision('approval-unowned',dict(outcome='allowed-once'),outsider.agent)
        receipt=await ctx.subagents.startActivation(dict(provider='spawn',parent=root,label='child',delivery='caller',signal=fixture.signal,prompt=[dict(type='text',text='hold')]))
        await decision('approval-descendant',dict(outcome='allowed-once'),ctx.agents.get(receipt['childId']))
        await receipt['dispose']();await outsider.dispose();await handle.dispose();await decision('approval-stale',dict(outcome='allowed-once'))
        return rows
    finally:await server.shutdown();await ctx.fiber.dispose()


WORKSPACE=None
def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_interaction.mts','Actual SDK question bridge and approval waterfall compare host answer validation, disabled/unowned fallback, original error taxonomy, cancellation notices, close, exact root/descendant ownership and stale Agent refusal. Generated question request ids excluded; real activation subtree used for approval ownership.',[Path(__file__).resolve(),ROOT/'dsh/sdk/server.py',ROOT/'dsh/sdk/user_questions.py'],prepare=prepare)
