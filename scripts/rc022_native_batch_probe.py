"""Exercise actual native batch providers with cancellation and durable failures."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin, NativeToolExecutor
    from dsh.core.session.current_session import CurrentSession
    from dsh.llm.message import create_user_message
    rows=[]
    for action in ('standalone','owned-unlogged','logged','parallel','exclusive','override','cancel-before','cancel-body','conditional','partial'):
        ctx=Context();await ctx.plugin(SystemPrompt);await ctx.plugin(CurrentToolsPlugin)
        if action=='override':ctx.tools.setExecutor(NativeToolExecutor(ctx,lambda:1))
        else:await ctx.plugin(NativeToolExecutorPlugin)
        session=CurrentSession.create('batch',format_version=4)
        agent=SimpleNamespace(ctx=ctx,session=session)
        signal=AbortController();trace=[];active=0;peak=0;ended=[];second=asyncio.Event();primary=RuntimeError('result write failed')
        async def body(args,execution):
            nonlocal active,peak
            i=args['i'];trace.append(i);active+=1;peak=max(peak,active)
            if action in ('parallel','override'):
                if i==0:await second.wait()
                if i==1:second.set()
            if action=='cancel-body':signal.abort(RuntimeError('cancel'))
            execution.deferContext(create_user_message(dict(content=[dict(type='text',text='context-'+str(i))],source=dict(kind='plugin',pluginId='fixture'))))
            if i==1:execution.concludeTurn()
            active-=1;ended.append(i)
            return str(i)
        definition=dict(name='work',description='work',parameters=dict(type='object',properties=dict(i=dict(type='integer')),required=['i']),
                        output=dict(schema=dict(type='string'),render=lambda a,v:[dict(type='text',text=v)]),execute=body,
                        isConcurrencySafe=lambda args:action in ('parallel','override'))
        ctx.tools.register(definition,dict(when=lambda c:True) if action=='conditional' else {})
        if action=='partial':
            append=session.append
            def checked(kind,data,**kwargs):
                if kind=='tool/result' and data['message']['toolCallId']=='c1':raise primary
                return append(kind,data,**kwargs)
            session.append=checked
        input=dict(calls=[dict(type='tool-call',id='c'+str(i),name='work',arguments=json.dumps(dict(i=i))) for i in range(3)],signal=signal.signal)
        if action!='standalone':input['agent']=agent
        if action in ('logged','partial'):input['log']=dict(turn=1,step=1)
        if action=='override':input['maxParallelToolCalls']=2
        selection=None
        if action=='conditional':
            selection=await ctx.tools.resolve(dict(agent=agent,modelSelection={},signal=signal.signal));input['toolSet']=selection
        if action=='cancel-before':signal.abort(RuntimeError('cancel'))
        row=dict(action=action)
        try:
            result=await ctx.tools.execute(input)
        except Exception as error:
            row['error']=dict(name=type(error).__name__,cause=error.cause is primary)
            result=error.partial
        row['results']=[dict(callId=item['callId'],value=item['result'].error['info']['code'] if item['result'].is_error else item['result'].value) for item in result['results']]
        row['contexts']=[message['content'][0]['text'] for message in result['additionalContexts']]
        row.update(concluded=result['concluded'],trace=trace,peak=peak,drained=active==0,ended=sorted(ended))
        row['events']=[dict(type=event['type'],seq=event['seq'],callId=event['data']['callId'] if event['type']=='tool/call' else event['data']['message']['toolCallId']) for event in session.events]
        rows.append(row)
        if selection is not None:selection.dispose()
        await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_native_batch.mts','Actual native provider: ordered batches, optional logging/ownership, parallel pools/barriers, explicit limits, admission, cancellation, partial failure and quiescence.',[Path(__file__).resolve(),ROOT/'dsh/core/tools.py',ROOT/'dsh/core/tool_calls.py',ROOT/'dsh/core/tool_executor_native.py'])
