"""Original current Guest on the native private VM carrier, with actual Host."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=ROOT/'tests/fixtures/rc022_workflow_guest.json'


async def observe():
    from dsh.cordis import Context
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.workflow.ptc_executor import QuickJsWorkflowExecutor
    from dsh.workflow.ptc_run import PtcWorkflowRun
    ctx=Context();await ctx.plugin(JavaScriptRuntime);native=ctx.jsRuntime;rows=[]
    class Directory:
        async def ensure(self,*_):return 'C:/fixed-work'
    ctx.provide('workingDirectory');ctx.set_service('workingDirectory',Directory())
    try:
        for case in json.loads(CASES.read_text(encoding='utf-8')):
            events=[];requests=[];closed=[];active=[0,0]
            async def start(spec):
                index=len(requests)+1
                requests.append(dict(cwd=spec['cwd'],label=spec['label'],delivery=spec['delivery'],prompt=spec['prompt'],options=spec.get('agentOptions'),schema=spec.get('outputSchema')))
                active[0]+=1;active[1]=max(active[1],active[0])
                async def result():
                    await asyncio.sleep(.15 if index==2 else .005)
                    return dict(output=[dict(type='text',text='reply:'+spec['prompt'][0]['text'])],stopReason=case.get('childStop','completed'),structured=dict(ok=True))
                async def dispose():closed.append(index);active[0]-=1
                return SimpleNamespace(childId='child-'+str(index),result=asyncio.create_task(result()),dispose=dispose)
            def event(name):return lambda value:events.append(dict(type=name,value=value))
            observer=SimpleNamespace(phase=event('phase'),log=event('log'),agentStart=event('start'),agentEnd=event('end'))
            init=dict(meta=dict(name=case['name'],description='current Guest'),body=case['body'],limits=dict(maxConcurrentAgents=case.get('concurrent',2),maxTotalAgents=case.get('total',20),maxItemsPerCall=case.get('items',100),syncTimeoutMs=case.get('timeout',1000)))
            if 'args' in case:init['args']=case['args']
            run=PtcWorkflowRun(ctx,SimpleNamespace(startActivation=start),QuickJsWorkflowExecutor(native),'run',init['meta'],None,init,'stub',dict(mode='read-only'),observer)
            result=await run.result;await run.dispose()
            if 'error' in result:
                result['error']=result['error'].splitlines()[0]
                if case['name'] in ('sync-timeout','syntax'):result['error']=case['name']
            rows.append(dict(name=case['name'],result=result,events=events,requests=requests,closed=sorted(closed),maxActive=active[1],workers=len(native._workers)))
        return rows
    finally:await ctx.fiber.dispose()


def prepare(output):return [CASES]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workflow_guest.mts','Actual current Host and byte-preserved Guest execute in native QuickJS private realm versus original Guest in Source Node VM. Controlled activation port; error stack frames excluded and only syntax/VM timeout diagnostics classified by exercised failure kind.',[Path(__file__).resolve(),CASES,ROOT/'dsh/workflow/ptc_executor.py',ROOT/'dsh/workflow/ptc_run.py'],prepare=prepare)
