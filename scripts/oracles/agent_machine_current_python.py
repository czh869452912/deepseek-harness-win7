"""Retained v3 machine-contract compatibility observations.

The original archived journeys predate the v4 lifecycle creator field. The
explicit v3 notification view below preserves that old DTO for comparison; full
current lifecycle/SDK DTOs are qualified separately by rc022 probes.
"""
import asyncio
import json
import os
import re
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from dsh.cordis.context import Context
from dsh.core.session.current_session import CurrentSession, CurrentSessionPlugin
from dsh.core.session.json import UNDEFINED
from dsh.typert.artifact import UNDEFINED as WIRE_UNDEFINED
from dsh.session.projections import SessionProjectionsPlugin
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.core.agent_current import CurrentAgentPlugin
from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
from dsh.llm.runtime_current import CurrentLlmRuntime
from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin


def legacy_lifecycle_notification(name, payload):
    """Project just the added creator field out of the old v3 DTO contract."""
    if name not in ('subagent/start', 'subagent/end'):
        raise ValueError('Only the retained v3 lifecycle DTO is supported')
    if not isinstance(payload.get('parentSessionId'), str):
        raise ValueError('Current lifecycle notification must retain its creator')
    return dict(name=name, payload={key: value for key, value in payload.items()
                                   if key != 'parentSessionId'})


def bind_retained_sdk_subagent_shutdown(ctx):
    """Map the retained v3 provider's real drain to the current SDK boundary.

    Only this historical observation fixture mounts CurrentSubagentRuntime;
    production profiles use the current SubagentRuntime directly.
    """
    from dsh.subagent.runtime_current import CurrentSubagentRuntime
    service = ctx.get('subagents')
    original = getattr(service, 'cordis.original')
    if not isinstance(original, CurrentSubagentRuntime):
        raise TypeError('Retained SDK fixture requires its explicit v3 subagent provider')
    adapter = patch.object(original, 'drainDescendants',
                           service.drainContinuableDescendants, create=True)
    adapter.start()
    ctx.effect(lambda: adapter.stop)


class ScriptAdapter:
    def __init__(self,test):self.test=test;self.script=list(test.get('script',[]))
    async def resolve_model(self,provider,model,signal=None):
        info=dict(provider=provider,id=model,name=model)
        for key in ('reasoning','defaultMaxTokens','systemPromptUpdate'):
            if key in self.test:info[key]=self.test[key]
        return info
    async def stream(self,request):
        if not self.script:raise RuntimeError('MockAdapter: script exhausted')
        entry=self.script.pop(0)
        hanging=entry=='hang' or isinstance(entry,dict) and 'hangAfter' in entry
        chunks=([dict(type='block-start',index=0,blockType='text'),dict(type='text-delta',index=0,text='partial')] if entry=='hang'
                else entry['hangAfter'] if hanging else entry)
        for chunk in chunks:yield chunk
        if hanging:
            future=asyncio.get_running_loop().create_future()
            def abort(*args):
                if not future.done():future.set_exception(RuntimeError('aborted'))
            remove=request['signal'].add_listener('abort',abort)
            if request['signal'].aborted:abort()
            try:await future
            finally:remove()


async def run(test,decode):
    ctx=Context();ids={};requests=[];notifications=[];results=[];errors=[];forward_controller=None;connection_routes={};feedback_version=None
    handle=None;agent=None;sdk=None;event_stream=None;event_controller=None;event_ready=None;event_frame=None;forward=None;prompt=test.get('prompt','prompt one');route=test.get('options',dict(provider='script',model='model'));pre_step=test.get('preStep',{});retry=stopped=chunks=0
    def normalize(value,key=''):
        if value is UNDEFINED or value is WIRE_UNDEFINED:return None
        if key=='signal':return '<signal>'
        if key=='agent':return normalize(value.id)
        if isinstance(value,BaseException):
            result=dict(name=getattr(value,'name','TypeError' if isinstance(value,TypeError) else 'Error'),message=normalize(getattr(value,'message',str(value))))
            if hasattr(value,'code'):result['code']=value.code
            if getattr(value,'cause',None) is not None:result['cause']=normalize(value.cause)
            return result
        if isinstance(value,str):
            def identity(match):
                name=match.group()
                if name not in ids:ids[name]='generated:'+str(len(ids)+1)
                return ids[name]
            return re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|cmd-[0-9a-f]{8}-[1-9][0-9]*',identity,value,flags=re.I)
        if isinstance(value,(tuple,list)):return [normalize(item) for item in value]
        if isinstance(value,dict):return {name:normalize(item,name) for name,item in value.items() if item is not UNDEFINED and item is not WIRE_UNDEFINED}
        return value
    def view():
        values=ctx.get('sessionProjections').snapshot(agent.session)['values']
        return normalize(dict(status=agent.status,events=agent.session.snapshotEvents(),messages=agent.session.deriveMessages(),**(dict(inbox=values['inbox']) if 'inbox' in values else {})))
    with tempfile.TemporaryDirectory(prefix='dsh-machine-pair-') as folder,patch.object(CurrentSession,'_event_time',return_value=1000),patch('dsh.core.assistant_stream_current.time.time',return_value=1),patch('dsh.goal.service.time.time',return_value=1),patch('dsh.feedback.message_current.time.time',return_value=1):
        try:
            for plugin in (CurrentLlmRuntime,CurrentSessionPlugin,SessionProjectionsPlugin,CurrentSystemPrompt,ToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin,test.get('promptConfig') if plugin is CurrentSystemPrompt else None)
            if test.get('meter'):
                from dsh.llm.token_meter_current import CurrentTokenMeterPlugin
                await ctx.plugin(CurrentTokenMeterPlugin)
            if test.get('persistence'):await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=folder,compression=test.get('compression','none')))
            if test.get('subagents'):
                from dsh.session.query_current import CurrentSqliteSessionQueryPlugin
                from dsh.subagent.runtime_current import CurrentSubagentPlugin
                from dsh.subagent.in_process_current import CurrentSpawnInProcess,CurrentForkInProcess
                await ctx.plugin(CurrentSqliteSessionQueryPlugin,dict(path=':memory:',openAt='never'))
                for plugin in (CurrentSubagentPlugin,CurrentSpawnInProcess,CurrentForkInProcess):await ctx.plugin(plugin)
                for name in ('subagent/start','subagent/end'):ctx.on(name,lambda payload,key=name:notifications.append(normalize(legacy_lifecycle_notification(key,payload))))
            await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
            if test.get('goals'):
                from dsh.goal.current import CurrentGoalService,CurrentGoalRoundDriver
                await ctx.plugin(CurrentGoalService,test.get('goalConfig'))
                if test.get('goalDriver'):await ctx.plugin(CurrentGoalRoundDriver)
                if test.get('goalTools'):
                    from dsh.goal.current import CurrentToolGoal
                    await ctx.plugin(CurrentToolGoal,test.get('goalToolConfig'))
                for name in ('goal/changed','goal/activation-changed'):
                    ctx.on(name,lambda payload,key=name:notifications.append(normalize(dict(name=key,payload=payload))))
            ctx.get('llm').registerAdapter(['script'],ScriptAdapter(test))
            async def assemble(assembly,context,next):
                result=dict(await next());result['sections']=[dict(name='test',text=prompt)];result['contexts']=[dict(name='policy',text=test['context'])] if test.get('context') else []
                return result
            async def propose(payload,next):return dict(await next(),**route)
            async def before_step(payload,next):
                if pre_step.get('kind')=='reject':return dict(kind='reject')
                result=dict(await next())
                if pre_step.get('empty'):result['messages']=[]
                if pre_step.get('startsRequestSeries'):result['startsRequestSeries']=True
                return result
            async def request_error(payload,next):
                nonlocal retry
                value=retry;retry+=1
                return dict(kind='retry') if value<test.get('retries',0) else await next()
            def stopping(payload):
                nonlocal stopped
                value=stopped;stopped+=1
                if value<len(test.get('stopping',[])):payload['agent'].inject(test['stopping'][value])
            def stream(request,next):requests.append(normalize(request));return next()
            if not test.get('realPrompt'):ctx.on('system-prompt/assemble',assemble)
            ctx.on('agent/request',propose);ctx.on('agent/pre-step',before_step);ctx.on('agent/request-error',request_error);ctx.on('agent/turn-stopping',stopping);ctx.on('llm/stream',stream)
            def notify(name,payload):
                nonlocal chunks
                notifications.append(normalize(dict(name=name,payload=payload)))
                if (name=='agent/assistant-stream' and payload['frame']['type']=='chunk'
                        and payload['frame']['chunk']['type']=='text-delta' and test.get('modelPause')):
                    current=ctx.get('goals').get(payload['agent'])
                    if current['phase']=='active':ctx.get('goals').pause(payload['agent'],dict(id=current['id'],revision=current['revision']))
                if name=='agent/assistant-stream' and payload['frame']['type']=='chunk' and test.get('cancelAfter'):
                    chunks+=1
                    if chunks==test['cancelAfter']:payload['agent'].cancel(dict(kind='user'))
                if name=='agent/session-start' and test.get('startMessage'):payload['agent'].followup(test['startMessage'])
            for name in ('agent/created','agent/disposed','agent/session-start','agent/status','agent/assistant-stream','agent/inbox/inserted','agent/inbox/discarded','agent/inbox/claimed'):
                if test.get('throwNotification')==name:
                    def fail(*args):raise RuntimeError('observer failure')
                    ctx.on(name,fail)
                ctx.on(name,lambda payload,key=name:notify(key,payload))
            ctx.on('agent/error',lambda payload:errors.append(normalize(payload['error'])))
            meta=dict(createdAt=1000)
            if test.get('cwd'):meta['cwd']=os.getcwd()
            handle=await ctx.get('agents').create(dict(sessionId='machine',agentOptions=test.get('options',dict(provider='script',model='model')),meta=meta));agent=handle.agent
            for action in test['actions']:
                try:
                    value=None;method=action['method']
                    if method=='prompt':prompt=action['text']
                    elif method=='canonicalZone':
                        from dsh.util_time import canonical_client_time_zone
                        value=canonical_client_time_zone(action['value'])
                    elif method=='feedbackCommandConfig':
                        from dsh.interaction.commands import CommandsPlugin
                        from dsh.feedback.session_current import CurrentCommandFeedback
                        await ctx.plugin(CommandsPlugin);await ctx.plugin(CurrentCommandFeedback)
                    elif method=='feedbackCommand':
                        from dsh.core.abort import AbortController
                        with patch.dict(os.environ,dict(DSH_HOME=folder)):
                            value=await ctx.get('commands').execute(agent,'/feedback'+action.get('suffix',''),[],AbortController().signal)
                        if value is not None:value=dict(commandId=value.commandId,result=value.result)
                    elif method=='feedbackConfig':
                        from dsh.feedback.session_current import CurrentSessionFeedback
                        from dsh.feedback.message_current import CurrentMessageFeedback
                        await ctx.plugin(CurrentSessionFeedback)
                        await ctx.plugin(CurrentMessageFeedback,dict(maxNoteBytes=action.get('maxNoteBytes',32)))
                        ctx.on('feedback/committed',lambda inspection:notifications.append(normalize(dict(name='feedback/committed',payload=inspection))))
                    elif method=='sessionFeedback':value=await ctx.get('sessionFeedback').record(dict(sessionId=action.get('sessionId','machine'),**action.get('entry',{})))
                    elif method=='messageFeedback':
                        request=dict(sessionId=action.get('sessionId','machine'),**action.get('request',{}))
                        if action['operation']!='list':
                            request.setdefault('messageId',next((m['id'] for m in agent.session.deriveMessages() if m['role']=='assistant'),'missing'))
                            request.setdefault('ifVersion',feedback_version if action.get('currentVersion') else None)
                        value=await getattr(ctx.get('messageFeedback'),action['operation'])(request)
                        if value.get('ok') and isinstance(value.get('value'),dict) and 'version' in value['value']:feedback_version=value['value']['version']
                    elif method=='messageFeedbackBatch':
                        message_id=next(m['id'] for m in agent.session.deriveMessages() if m['role']=='assistant')
                        value=await asyncio.gather(*(ctx.get('messageFeedback').put(dict(sessionId='machine',messageId=message_id,ifVersion=None,**request)) for request in action['requests']))
                    elif method=='connectionHttp':
                        from scripts.oracles.connection_http_current_python import execute as http_execute
                        value=await http_execute(action)
                    elif method=='connectionConfig':
                        from dsh.host.connection.current import CurrentConnectionPlugin
                        records={}
                        def modify(key,mutator):
                            value=mutator(records.get(key))
                            if value is not None:records[key]=value
                            return records.get(key)
                        ctx.set_service('credentials',SimpleNamespace(modify_record=modify))
                        await ctx.plugin(CurrentConnectionPlugin,action.get('config'))
                        value=dict(available=ctx.get('connection') is not None,webServer=ctx.get('webServer') is not None)
                    elif method=='connectionRecovery':
                        from dsh.host.connection.current import resolve_connection_config
                        value=resolve_connection_config(decode(action.get('config',{})))
                    elif method=='connectionRoute':
                        route=dict(action['route'],fetch=lambda request:dict(status=202,body='exact'))
                        connection_routes[route['path']]=ctx.get('connection').fetch.register(route)
                    elif method=='connectionWithdraw':
                        from dsh.cordis.awaiting import await_callback_result
                        await await_callback_result(connection_routes[action['path']]())
                    elif method=='connectionRequest':
                        from dsh.typert.artifact import UNDEFINED as WireUndefined
                        connection=ctx.get('connection')
                        if action.get('intercept'):
                            connection.rpc.intercept('/api',lambda _:True,lambda *args:dict(ok=True,value=WireUndefined))
                        shared=connection.createSharedFetchHandler('/api')
                        request=dict(path=action.get('path','/api/test/run'),method=action.get('verb','POST'),headers={'content-type':action.get('contentType','application/json')},body=json.dumps(action.get('body')).encode('utf-8'))
                        result=await shared.fetch(request)
                        value=dict(mode=shared.requestBodyMode(request),status=result['status'],body=result.get('body',''))
                    elif method=='remoteConfig':
                        from dsh.typert.current import CurrentTypertRegistry,CurrentTypertGateway,CurrentApiRemotes
                        for plugin in (CurrentTypertRegistry,CurrentTypertGateway,CurrentApiRemotes):await ctx.plugin(plugin)
                    elif method=='remote':
                        from dsh.core.abort import AbortController
                        value=await ctx.get('typertGateway').invoke(dict(namespace=action['namespace'],method=action['name'],args=action['args'],signal=AbortController().signal))
                    elif method=='remoteContext':
                        adapter=ctx.get('typert').contexts.getHost('agent')
                        from dsh.cordis.awaiting import await_callback_result
                        target=await await_callback_result(adapter['resolve']('machine') if isinstance(adapter,dict) else adapter.resolve('machine'))
                        value=dict(exact=target is agent.ctx,identityPresent=('identity' in adapter if isinstance(adapter,dict) else hasattr(adapter,'identity')),reversePresent=hasattr(ctx.get('typert').contexts,'identifyHost'))
                    elif method=='eventsOpen':
                        from dsh.core.abort import AbortController
                        event_controller=AbortController()
                        event_stream=await ctx.get('typertGateway').wireStream.open('$events',dict(args={}),event_controller.signal)
                        event_ready=await event_stream.__anext__();value=event_ready
                    elif method=='eventsNext':event_frame=await asyncio.wait_for(event_stream.__anext__(),3);value=event_frame
                    elif method=='forward':
                        from dsh.core.agent_dispatch_current import agent_carrier
                        request=dict(action.get('request',{}),agent=agent)
                        if action.get('withSignal'):
                            from dsh.core.abort import AbortController
                            forward_controller=AbortController();request['signal']=forward_controller.signal
                        if action.get('wrongAgent'):request['agent']=None
                        forward=asyncio.ensure_future(ctx.waterfall(agent_carrier(agent),action.get('event','approval/request'),request,lambda *_:dict(fallback=True)))
                    elif method=='forwardAbort':forward_controller.abort(action['reason'])
                    elif method=='eventsResult':
                        from dsh.core.abort import NEVER_ABORTED
                        value=await ctx.get('typertGateway').dispatch_rpc('$events/result',dict(args=dict(clientId=event_ready['clientId'],eventId=event_frame['eventId'],outcome=action['outcome'])),NEVER_ABORTED)
                    elif method=='forwardResult':value=await asyncio.wait_for(forward,3)
                    elif method=='sdkConfig':
                        from dsh.sdk.server import HarnessSdkJsonRpcServer
                        if test.get('subagents'):
                            bind_retained_sdk_subagent_shutdown(ctx)
                        sdk=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda name,params:notifications.append(normalize(dict(name=name,payload=params)))),action.get('options'))
                    elif method=='sdkInitialize':
                        value=await sdk.initialize(dict(dict(cwd=os.getcwd(),provider='script',model='model'),**action.get('params',{})))
                    elif method=='sdkPrompt':value=await sdk.prompt(action['params'])
                    elif method=='sdkBatch':value=await asyncio.gather(*(sdk.prompt(params) for params in action['params']))
                    elif method=='sdkIdle':await ctx.get('agents').get(action['id']).whenIdle()
                    elif method=='sdkView':
                        subject=ctx.get('agents').get(action['id'])
                        value=dict(status=subject.status,events=subject.session.snapshotEvents(),messages=subject.session.deriveMessages()) if subject else None
                    elif method=='sdkShutdown':value=await sdk.shutdown()
                    elif method=='goal':
                        goals=ctx.get('goals');operation=action['operation']
                        if operation=='create':value=goals.create(agent,action['request'])
                        elif operation in ('get','disarm'):value=getattr(goals,operation)(agent)
                        else:
                            current=goals.get(agent)
                            ref=action.get('ref',dict(id=current['id'],revision=current['revision']) if current else dict(id='missing',revision=1))
                            args=[agent,ref]
                            if operation=='edit':args.append(action.get('request',{}))
                            if operation=='block':args.append(action.get('reason'))
                            value=getattr(goals,operation)(*args)
                    elif method=='goalProjection':value=ctx.get('sessionProjections').stateOf(agent.session,'goal')
                    elif method=='goalTool':
                        from dsh.core.abort import AbortController
                        current=ctx.get('goals').get(agent)
                        args=dict(action.get('args',{}));deferred=[]
                        if action['name']=='update_goal':args=dict(dict(goal_id=current['id'],revision=current['revision']),**args)
                        execute=ctx.get('tools').get(action['name'],agent).execute
                        run=SimpleNamespace(agent=agent,signal=AbortController().signal,deferContext=deferred.append)
                        call=execute(args,run)
                        result=await ctx.get('agents').with_initiator_async(agent,call) if action.get('initiated',True) else await call
                        value=dict(result=result,deferred=deferred)
                    elif method=='entered':
                        deadline=asyncio.get_running_loop().time()+3
                        while not any(n['name']=='agent/assistant-stream' and n['payload']['frame']['type']=='chunk' and n['payload']['frame']['chunk']['type']=='text-delta' for n in notifications):
                            if asyncio.get_running_loop().time()>deadline:raise RuntimeError('Stream entry deadline')
                            await asyncio.sleep(.001)
                    elif method=='appendEvent':value=agent.session.append(action['type'],action['data'])
                    elif method=='goalSettled':
                        deadline=asyncio.get_running_loop().time()+3
                        while ctx.get('goals').get(agent)['phase']!=action['phase']:
                            if asyncio.get_running_loop().time()>deadline:raise RuntimeError('Goal settlement deadline')
                            await asyncio.sleep(.001)
                        await agent.whenIdle()
                    elif method=='measure':value=ctx.get('tokenMeter').measure(agent.session,action.get('header'))
                    elif method=='meterProjections':value=ctx.get('sessionProjections').snapshot(agent.session,['tokenUsage','contextPressure','contextBreakdown'])
                    elif method=='compact':
                        from dsh.core.abort import AbortController
                        from dsh.compaction.current import CurrentCompactionBasic
                        await ctx.plugin(CurrentCompactionBasic,dict(auto=False))
                        value=await ctx.get('compaction').compactNow(agent,AbortController().signal)
                    elif method=='selectionSettings':
                        from dsh.subagent.model_selection import ModelSelectionSettings
                        await ctx.plugin(ModelSelectionSettings,action['config'])
                    elif method=='policySession':
                        session=ctx.get('sessions').create(action['id'])
                        session.append('subagent/model-selection-policy',dict(allowedModels=action['routes']))
                    elif method=='externalConfig':
                        import sys
                        from pathlib import Path
                        from dsh.subprocess.local import LocalSubprocessRuntime
                        from dsh.subagent.acp_current import CurrentSubagentAcp
                        await ctx.plugin(LocalSubprocessRuntime)
                        await ctx.plugin(CurrentSubagentAcp,dict(command=sys.executable,args=[str(Path(__file__).with_name('subagent_acp_peer.py'))],env=action.get('env',{}),disposeEofGraceMs=150,disposeGraceMs=100))
                    elif method=='externalRun':
                        from dsh.core.abort import AbortController
                        run=await ctx.get('subagents').start('acp',dict(parent=agent,prompt=action['prompt'],signal=AbortController().signal))
                        try:value=dict(id=run.id,result=await run.result,localAgent=run.localAgent is not None)
                        finally:await run.dispose()
                    elif method=='toolConfig':
                        from dsh.subagent.canonical_tools_current import apply_tool_subagent,CurrentToolSubagent
                        target=agent.session if action.get('direct',True) else None
                        if 'target' in action:
                            options=dict(action['target']);sid=options.pop('id');target=ctx.get('sessions').prepare(sid,options)
                        failures=[]
                        def install(runtime_ctx):
                            try:apply_tool_subagent(runtime_ctx,action['config'],target)
                            except Exception as error:failures.append(error)
                        await agent.ctx.inject(CurrentToolSubagent.inject,install)
                        if failures:raise failures[0]
                        value=ctx.get('tools').schemas(agent)
                        if 'target' in action:value=dict(schemas=value,events=target.snapshotEvents())
                    elif method=='toolCall':
                        from dsh.core.abort import AbortController
                        tool=ctx.get('tools').get(action.get('name','subagent'),agent)
                        value=await tool.execute(action['payload'],SimpleNamespace(agent=agent,signal=AbortController().signal))
                    elif method=='listChildren':value=await ctx.get('subagents').listChildren(agent.id)
                    elif method=='persona':
                        from dsh.core.persona_current import CurrentPersonaPlugin
                        await agent.ctx.plugin(CurrentPersonaPlugin,action['config'])
                    elif method=='child':
                        from dsh.core.abort import AbortController
                        from dsh.subagent.in_process_current import start_run
                        from dsh.subagent.descriptor import completed_turn_prefix
                        seed=completed_turn_prefix(agent) if action.get('fork') else None
                        run=await start_run(dict(action['request'],parent=agent,signal=AbortController().signal),seed if seed else None)
                        result=await run.result
                        value=normalize(dict(id=run.id,result=result,header=run.localAgent.session.header.to_dict(),events=run.localAgent.session.snapshotEvents(),owned=ctx.get('agents').isOwnedBy(run.id,agent)))
                        await run.dispose()
                    elif method=='background':
                        from dsh.core.abort import AbortController
                        spec=dict(action['spec'],signal=AbortController().signal,request=dict(action['spec']['request'],parent=agent))
                        value=await ctx.get('subagents').startContinuable(spec)
                    elif method=='childIdle':
                        async def closed():
                            while ctx.get('agents').get(action['id']) is not None:await asyncio.sleep(.001)
                        await asyncio.wait_for(closed(),3);await agent.whenIdle()
                    elif method=='childObserve':
                        observed=await ctx.get('sessionQuery').observeSession(action['id'])
                        try:value=dict(header=observed.header.to_dict(),events=observed.events,inheritedEventCount=observed.inheritedEventCount)
                        finally:observed.dispose()
                    elif method=='childEntered':
                        async def entered():
                            while not any(n.get('name')=='agent/assistant-stream' and n['payload']['agent']==action['id'] and n['payload']['frame']['type']=='chunk' and n['payload']['frame']['chunk']['type']=='text-delta' for n in notifications):await asyncio.sleep(.001)
                        await asyncio.wait_for(entered(),3)
                    elif method=='childQuiescent':
                        child=ctx.get('agents').get(action['id']);await child.whenIdle()
                        value=dict(status=child.status,events=child.session.snapshotEvents(),inbox=ctx.get('sessionProjections').snapshot(child.session,['inbox'])['values']['inbox'])
                    elif method=='interruptChild':ctx.get('subagents').interrupt(action['id'],dict(kind='ancestor',agent=agent) if action.get('ancestor') else dict(kind='user',parentSessionId=action.get('parentId',agent.id)))
                    elif method in ('queueChild','sendChild'):
                        from dsh.core.abort import AbortController
                        if method=='queueChild':value=await ctx.get('subagents')._deliver_prompt(agent,action['id'],action['content'],action.get('source',dict(kind='user')),AbortController().signal,'queue')
                        else:value=await ctx.get('subagents').sendMessage(agent,action['id'],action['content'],dict(signal=AbortController().signal))
                    elif method=='serviceChild':
                        from dsh.core.abort import AbortController
                        run=await ctx.get('subagents').start(action['provider'],dict(action['request'],parent=agent,signal=AbortController().signal))
                        try:value=dict(id=run.id,result=await run.result,header=run.localAgent.session.header.to_dict(),events=run.localAgent.session.snapshotEvents())
                        finally:await run.dispose()
                    elif method=='route':route=action['config']
                    elif method=='preStep':pre_step=action['value']
                    elif method=='idle':await agent.whenIdle()
                    elif method=='view':value=view()
                    elif method=='resume':
                        await handle.dispose();handle=None
                        handle=await ctx.get('agents').resume(dict(resumeSessionId='machine',agentOptions=action.get('options',dict(provider='script',model='model'))));agent=handle.agent
                    elif method=='dispose':await handle.dispose();handle=None
                    else:value=getattr(agent,method)(*decode(action.get('args',[])))
                    results.append(dict(outcome='value',value=normalize(value)))
                except Exception as error:results.append(dict(outcome='error',error=normalize(error)))
            await agent.whenIdle();final=view()
            if handle is not None:await handle.dispose();handle=None
            return dict(results=results,final=final,requests=requests,notifications=notifications,errors=errors)
        finally:
            if event_controller is not None:event_controller.abort()
            if event_stream is not None:await event_stream.aclose()
            if sdk is not None:await sdk.shutdown()
            if handle is not None:await handle.dispose()
            await ctx.fiber.dispose()


def execute(test,decode):return asyncio.run(run(test,decode))
