"""Controlled executor observations of the actual current Workflow PTC Host."""
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def scenario(kind):
    from dsh.workflow.ptc_run import PtcWorkflowRun
    from dsh.core.abort import AbortController
    rows=[];entered=asyncio.Event();release=asyncio.Event();launched=asyncio.Event();external=AbortController()
    directory=['C:/initial'];calls=[];disposed=[];warnings=[]
    async def ensure(parent,signal):
        calls.append('cwd')
        if kind=='directory-failure':raise ValueError('selected directory unavailable')
        return directory[0]
    ctx=SimpleNamespace(get=lambda name:SimpleNamespace(ensure=ensure),logger=SimpleNamespace(warn=warnings.append))
    async def start(spec):
        calls.append(dict(provider=spec['provider'],label=spec['label'],delivery=spec['delivery'],cwd=spec['cwd'],prompt=spec['prompt'],options=spec.get('agentOptions'),schema=spec.get('outputSchema')))
        entered.set()
        if kind=='late-child':await release.wait()
        future=asyncio.get_event_loop().create_future()
        if kind!='cancel-wait':future.set_result(dict(output=[dict(type='text',text='child')],stopReason='completed',structured=dict(ok=True)))
        async def dispose():
            disposed.append('child')
            if kind=='dispose-failure':raise ValueError('cleanup refused')
        return SimpleNamespace(childId='child',result=future,dispose=dispose)
    def event(name):return lambda value:rows.append(dict(event=name,value=value))
    observer=SimpleNamespace(phase=event('phase'),log=event('log'),agentStart=event('start'),agentEnd=event('end'))
    async def execute(spec):
        calls.append(dict(cwd=spec['cwd'],timeout=spec['timeoutMs'],policy=spec.get('sandboxPolicy'),global_=spec['bindings'][0]['global']))
        bindings=spec['bindings'][0]['functions'];initial=await bindings['begin']({});rows.append(dict(begin=copy.deepcopy(initial)));initial['meta']['name']='detached'
        if kind=='malformed-result':return dict(value=dict(stopReason='completed',agentsStarted=0))
        if kind=='execution-error':return dict(error=dict(kind='timeout',message='expired'))
        if kind=='validation':
            for name,value in [('startChild',{}),('startChild',dict(prompt='p',model=3)),('childResult',dict(callId=True)),('childResult',dict(callId=3)),('progress',{}),('progress',[dict(type='phase',title='must not emit'),dict(type='bad')]),('progress',[dict(type='agent-start',info=dict(seq=0,label='x',childId='child'))])]:
                try:await bindings[name](value)
                except Exception as error:rows.append(dict(rejected=str(error)))
        else:
            if kind=='fixed-cwd':directory[0]='C:/moved'
            child=await bindings['startChild'](dict(prompt='hello',provider='llm',model='m',schema=dict(type='object',properties={})))
            rows.append(dict(child=child))
            info=dict(seq=1,label='one',childId='child')
            await bindings['progress']([dict(type='phase',title='work'),dict(type='agent-start',info=info)])
            launched.set()
            try:rows.append(dict(childResult=await bindings['childResult'](child)))
            except Exception:rows.append(dict(childAborted=True))
            if kind!='open-progress':
                await bindings['progress']([dict(type='agent-end',info=dict(info,outcome='completed')),dict(type='agent-end',info=dict(info,outcome='completed'))])
                await bindings['disposeChild'](child)
        return dict(value=dict(value=7,stopReason='completed',agentsStarted=1))
    runtime=SimpleNamespace(sandboxMode=None if kind in ('unconfined','full-access') else 'read-only',programFormat='function-body',resolve=lambda spec:spec,run=execute)
    if kind=='already-aborted':external.abort('external')
    init=dict(meta=dict(name='host',description='contract'),body='return 7',limits=dict(maxConcurrentAgents=2,maxTotalAgents=10,maxItemsPerCall=20,syncTimeoutMs=1000))
    run=PtcWorkflowRun(ctx,SimpleNamespace(startActivation=start),runtime,'run',init['meta'],object(),init,'stub',dict(mode='danger-full-access' if kind=='full-access' else 'read-only'),observer,external.signal)
    if kind=='late-child':
        await entered.wait();run.cancel('stop');release.set()
    if kind=='cancel-wait':
        await launched.wait();run.cancel('stop')
    result=await run.result
    one=run.dispose();two=run.dispose();await one
    # Stack frames are runtime-specific; retain the actual message field only.
    if 'error' in result:result['error']=result['error'].splitlines()[0]
    rows.append(dict(result=result,calls=calls,disposed=disposed,warningCount=len(warnings),sameDisposal=one is two,pending=len(run.pending),children=len(run.children),originalMeta=init['meta']['name']))
    return dict(name=kind,rows=rows)


async def observe():
    return [await scenario(kind) for kind in ('normal','fixed-cwd','validation','open-progress','malformed-result','execution-error','directory-failure','unconfined','full-access','already-aborted','late-child','cancel-wait','dispose-failure')]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workflow_host.mts','Current Source/native PtcWorkflowRun with controlled runtime/activation/directory ports; observes host ownership, validation, cwd, policy admission and cleanup. Does not execute the Guest.',[Path(__file__).resolve(),ROOT/'dsh/workflow/ptc_run.py',ROOT/'dsh/workflow/ptc_guest.js'])
