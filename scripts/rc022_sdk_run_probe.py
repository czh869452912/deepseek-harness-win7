"""Pair the external SDK run coordinator with a deterministic client seam."""
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(kind='terminal',reason=reason) for reason in [None,dict(kind='completed'),dict(kind='max-tokens'),dict(kind='blocked'),dict(kind='error'),dict(kind='interrupted'),dict(kind='future'),*[dict(kind='aborted',reason=dict(kind=kind)) for kind in ('user','parent','disposed','legacy','hook')]]] + [dict(kind=kind) for kind in ('protocol','transport','unknown','malformed-event','malformed-reason','cancel','cancel-start','cancel-start-cleanup','startup','startup-aggregate','shutdown','sink-throws','pre-aborted')]


async def observe():
    from dsh.subagent import sdk_run as run
    from dsh.sdk.errors import SdkProtocolError,TransportClosedError
    from dsh.cordis.errors import AggregateError
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    original=run.internals.createHarness;rows=[]
    env_names=('RC022_AMBIENT_TOKEN','DSH_RC022_FACT')
    old={name:os.environ.get(name) for name in env_names}
    os.environ.update(RC022_AMBIENT_TOKEN='ambient',DSH_RC022_FACT='ambient')
    try:
        for case in cases():
            trace=[];reports=[];options={};queue=[];controller=AbortController();cancelled=asyncio.Event();closed=asyncio.Event();state={}
            if case['kind']=='pre-aborted':controller.abort()
            def raw_error(kind):return SdkProtocolError('private protocol') if kind=='protocol' else TransportClosedError('private transport') if kind=='transport' else RuntimeError('private failure')
            def publish(event):
                note=dict(method='session.event',params=dict(sessionId=state['session'],event=event))
                if state['filter'](note):queue.append(note)
            class Harness:
                def __init__(self):self.client=self
                async def start(self):
                    trace.append('start')
                    if case['kind'].startswith('cancel-start'):
                        controller.abort();await closed.wait();return
                    if case['kind'].startswith('startup'):
                        error=raw_error('protocol')
                        if case['kind']=='startup-aggregate':raise AggregateError([error,RuntimeError('private cleanup')],'private aggregate')
                        raise error
                def session(self,identity):state['session']=identity;return self
                async def setWorkingDirectory(self,cwd):trace.append(['cwd',cwd])
                def subscribe(self,predicate):
                    state['filter']=predicate
                    def take():return queue.pop(0) if queue else UNDEFINED
                    return NS(tryNext=take,close=lambda:trace.append('unsubscribe'))
                async def prompt(self,identity,prompt):
                    trace.append(['prompt',prompt]);state['session']=identity
                    publish(dict(type='assistant/attempt',data=dict(stream=[dict(type='text-chunks',time0=0,index=0,dt=[],texts=['partial'])])))
                async def request(self,method,params):
                    trace.append(method)
                    if case['kind'] in ('protocol','transport','unknown','sink-throws'):raise raw_error('unknown' if case['kind']=='sink-throws' else case['kind'])
                    if case['kind']=='cancel':controller.abort();await closed.wait();return
                    if case['kind']=='malformed-event':publish(1);return
                    if case['kind']=='malformed-reason':publish(dict(type='turn/end',data=dict(reason=dict(kind='aborted'))));return
                    publish(dict(type='assistant/message',data=dict(message=dict(content=[dict(type='text',text='answer')]),stream=[])))
                    if case.get('reason') is not None:publish(dict(type='turn/end',data=dict(reason=case['reason'])))
                async def close(self):
                    trace.append('close');closed.set()
                    if case['kind'] in ('shutdown','cancel-start-cleanup'):raise RuntimeError('private cleanup')
            def create(received):options.update(received);return Harness()
            run.internals.createHarness=create
            def report(error,reason):
                reports.append([type(error).__name__,reason])
                if case['kind']=='sink-throws':raise RuntimeError('sink failure')
            spec=dict(profile='sdk',patches=['patch'],dshHome='home',cwd='child',originCwd='origin',provider='provider',model='model',reasoningEffort='low',maxTokens=12,
                env=dict(RC022_AMBIENT_TOKEN='explicit'),shutdownTimeoutMs=1000,disposeEofGraceMs=6000,disposeGraceMs=3000,onError=report)
            def failure(error):
                return dict(name=getattr(error,'name',type(error).__name__),message=str(error),errors=[failure(e) for e in error.errors] if isinstance(error,AggregateError) else [])
            try:
                handle=await run.start_sdk_run(dict(signal=controller.signal,prompt=[dict(type='text',text='task')]),spec)
                result=await handle.result
                first=handle.dispose();second=handle.dispose()
                try:await first;disposal=None
                except Exception as error:disposal=failure(error)
                value=dict(result=result,sameDisposal=first is second,disposal=disposal)
            except Exception as error:value=dict(startFailure=failure(error))
            rows.append(dict(value=value,trace=trace,reports=reports,options={key:options[key] for key in ('profile','patches','dshHome','processCwd','cwd','provider','model','reasoningEffort','maxTokens') if key in options},
                environment={key:options.get('env',{}).get(key) for key in env_names},listeners=len(controller.signal._listeners)))
            await asyncio.sleep(0)
        return rows
    finally:
        run.internals.createHarness=original
        for name,value in old.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_run.mts','SDK run coordinator: ready-before-publication, route and cwd handshake options, environment scrub, terminal mapping, partial output, protocol/transport-safe errors, cancellation, startup aggregates and shared shutdown. Controlled client seam; actual pipe/process verification is separate.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/sdk_run.py',ROOT/'dsh/sdk/event_validation.py',ROOT/'dsh/sdk/errors.py'],prepare=prepare)
