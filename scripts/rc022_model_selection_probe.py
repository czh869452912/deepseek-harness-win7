"""Observe V4 Agent model choices, notices and fixed-step request routing."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

def cases():
    rows=[]
    for options in ({},{'provider':'alpha','model':'a0','reasoningEffort':'high'}):
        for effort in (None,'high','low'):
            for defaulted in (False,True):
                rows.append(dict(operation='model',options=options,effort=effort,defaulted=defaulted))
    for kind in ('initial','same','effort','changed','same-provider','rejected','aborted','empty-first','empty-offered','empty-continuation','disposed','long'):
        rows.append(dict(operation='notice',kind=kind))
    for kind in ('initial','persisted','defaults','route-change','effort-change','effort-add','effort-drop','controls'):
        rows.append(dict(operation='request',kind=kind))
    return rows

def clean(value):
    from dsh.core.session.json import UNDEFINED
    if value is UNDEFINED:return None
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('id','time') and v is not UNDEFINED}
    return value

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.model_selection import AgentModel,MODEL_SELECTION_PROJECTION_DEFINITION,install_model_selection
    from dsh.core.session.current_session import CurrentSessionStore,CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.abort import AbortController
    from dsh.core.agent_dispatch_current import agent_events
    from dsh.core.react_loop_current import ReactLoopAgent
    from dsh.core.agent import AgentOptions
    from dsh.core.session.json import UNDEFINED
    rows=[]
    for test in cases():
        ctx=Context()
        class Store(Plugin):
            def apply(self,owner):CurrentSessionStore(owner,4)
        class Registry(Plugin):
            def apply(self,owner):SessionProjectionRegistry(owner,4)
        try:
            await ctx.plugin(Store);await ctx.plugin(Registry);registry=ctx.get('sessionProjections');handle=await registry.register(MODEL_SELECTION_PROJECTION_DEFINITION);session=ctx.get('sessions').create('model');options=dict(test.get('options',{}));model=AgentModel(handle.readerFor(session),session,options);row=dict(test=test)
            def header(config,defaults=None):session.append('request/header',dict(header=dict(config=config,**({} if defaults is None else dict(adapterDefaults=defaults))),reason='initial'))
            if test['operation']=='model':
                row['initial']=model.current();model.select(dict(provider='alpha',model='a0'));row['selected']=model.current();same=len(session.events);model.select(dict(provider='alpha',model='a0'));row['duplicateSkipped']=len(session.events)==same
                chosen=dict(provider='beta',model='b1',**({} if test['effort'] is None else dict(reasoningEffort=test['effort'])));model.select(chosen);chosen['model']='mutated';detached=model.current();detached['model']='mutated-again';row['detached']=model.current()
                header(dict(provider='other',model='b1'));row['unmatched']=handle.stateOf(session)
                config=dict(provider='beta',model='b1',**({} if test['effort'] is None else dict(reasoningEffort=test['effort'])))
                if test['defaulted'] and test['effort'] is None:config['reasoningEffort']='high'
                header(config,dict(reasoningEffort=True) if test['defaulted'] else None);state=handle.stateOf(session);row['state']=state;header(config,dict(reasoningEffort=True) if test['defaulted'] else None);row['sameState']=state is handle.stateOf(session)
                restored=CurrentSession.create('restored',session.snapshotEvents(),format_version=4);row['cold']=AgentModel(handle.readerFor(restored),restored,{}).current();row['wire']=registry.snapshot(session)['values'];await handle.dispose();row['retained']=model.current()
            elif test['operation']=='notice':
                kind=test['kind'];controller=AbortController();input_message=dict(role='user',source=dict(kind='user'),content=[dict(type='text',text='continue')]);agent=SimpleNamespace(id=session.id,session=session,ctx=ctx,options=options,model=model);dispose=install_model_selection(ctx)
                if kind!='initial':header(dict(provider='alpha',model='a0'))
                selected=dict(provider='beta',model='b1')
                if kind in ('same','effort'):selected=dict(provider='alpha',model='a0',**(dict(reasoningEffort='high') if kind=='effort' else {}))
                if kind=='same-provider':selected=dict(provider='alpha',model='a1')
                if kind=='long':selected=dict(provider='beta',model='b'*130)
                if kind=='aborted':controller.abort()
                if kind=='disposed':dispose()
                messages=[] if kind.startswith('empty-') else [input_message];offered=[] if kind=='empty-continuation' else [input_message];step=2 if kind in ('empty-offered','empty-continuation') else 1
                decision=dict(kind='reject') if kind=='rejected' else dict(kind='enter',messages=messages,startsRequestSeries=True)
                dispatch=agent_events(ctx,agent);payload=dict(turn=1,step=step,messages=offered,signal=controller.signal,modelSelection=selected)
                row['decision']=await dispatch.waterfall('agent/pre-step',payload,lambda:decision)
            else:
                kind=test['kind'];selection=dict(provider='alpha',model='a0',**(dict(reasoningEffort='high') if kind=='effort-drop' else {}));persisted=kind in ('persisted','defaults','controls')
                if persisted:header(dict(provider='old',model='old',reasoningEffort='low',maxTokens=99,temperature=0.3),dict(reasoningEffort=True,maxTokens=True) if kind=='defaults' else None)
                async def request(name,payload,terminal):
                    proposed=dict(terminal())
                    if kind=='route-change':proposed['model']='other'
                    if kind in ('effort-change','effort-add'):proposed['reasoningEffort']='low'
                    if kind=='effort-drop':proposed.pop('reasoningEffort',None)
                    return proposed
                async def prepare(config,signal):return dict(config=config)
                ctx.set_service('llm',SimpleNamespace(prepareCall=prepare));agent=SimpleNamespace(id=session.id,session=session,options=AgentOptions(provider='ignored',model='ignored',maxTokens=17),request_header_logged=persisted,dispatch=SimpleNamespace(waterfall=request),loop_ctx=ctx)
                try:row['config']=(await ReactLoopAgent._prepare_request(agent,1,1,AbortController().signal,selection))[0]
                except Exception as error:row['error']=str(error)
            rows.append(clean(row))
        finally:await ctx.fiber.dispose()
    return rows

def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_model_selection.mts','AgentModel state v3, detached and cold reads, adapter-defaulted effort, switch notices and fixed-step request controls/routing.',[Path(__file__).resolve(),ROOT/'dsh/core/model_selection.py',ROOT/'dsh/core/react_loop_current.py',ROOT/'dsh/core/agent_loop_current.py',ROOT/'dsh/core/agent_loop.py'],prepare=prepare)
