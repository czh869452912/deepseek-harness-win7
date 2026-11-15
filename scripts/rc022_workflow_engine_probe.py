"""Current engine start admission and lifecycle over controlled execution."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.workflow.ptc_engine import PtcWorkflowEngine
    ctx=Context();await ctx.plugin(JavaScriptRuntime);rows=[];events=[]
    async def ensure(*_):return 'C:/engine'
    for name,value in [('subagents',NS(getProvider=lambda name:object() if name in ('stub','override') else None)),('workingDirectory',NS(ensure=ensure)),('sandboxPolicy',NS(resolve=lambda _:dict(mode='read-only')))]:ctx.set_service(name,value)
    owner=await ctx.plugin(PtcWorkflowEngine,dict(provider='stub',maxConcurrentAgents=2,maxTotalAgents=3));engine=ctx.workflowEngine
    for name in ('start','phase','end'):
        ctx.on('workflow/'+name,lambda info,*rest,name=name:events.append(dict(event=name,meta=info['meta'],data=list(rest))))
    requests=[]
    async def execute(spec):
        bindings=spec['bindings'][0]['functions'];initial=await bindings['begin']({});requests.append(initial)
        await bindings['progress']([dict(type='phase',title='working')])
        return dict(value=dict(value=initial.get('args'),stopReason='completed',agentsStarted=0))
    engine.executor=NS(sandboxMode='read-only',programFormat='function-body',resolve=lambda spec:spec,run=execute)
    parent=NS(session=object())
    base=dict(script='return 7',meta=dict(name='engine',description='admission'),parent=parent)
    try:
        cases=[('meta-object',dict(meta=None)),('meta-unknown',dict(meta=dict(name='engine',description='d',unknown=1))),('export',dict(script='export const meta = {}')),('syntax',dict(script='return )')),('provider-empty',dict(subagentProvider='')),('provider-space',dict(subagentProvider=' stub')),('provider-missing',dict(subagentProvider='missing')),('cap-zero',dict(maxTotalAgents=0)),('cap-float',dict(maxTotalAgents=1.5)),('cap-bool',dict(maxTotalAgents=True)),('cap-ceiling',dict(maxTotalAgents=4))]
        for name,patch in cases:
            try:engine.start(dict(base,**patch))
            except Exception as error:rows.append(dict(name=name,code=getattr(error,'code',None),error='syntax' if name=='syntax' else getattr(error,'message',str(error)),events=len(events)))
        args=dict(value=[1]);request=dict(base,args=args,maxTotalAgents=2,subagentProvider='override');run=engine.start(request);args['value'].append(2)
        result=await run.result;await asyncio.sleep(0);await run.dispose()
        rows.append(dict(name='run',result=result,events=events,initial=requests,infoMeta=run.meta))
        return rows
    finally:await owner.dispose();await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workflow_engine.mts','Current engine admission ordering, route/cap/meta/parse diagnostics, detached args, event ordering and private-value exclusion. Controlled executor in both; Native parses with shipped worker. Native explicitly injects private JavaScript executor instead of Node TypeScript ptcRuntime.',[Path(__file__).resolve(),ROOT/'dsh/workflow/ptc_engine.py'])
