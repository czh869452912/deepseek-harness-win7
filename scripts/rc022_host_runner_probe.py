"""Current runner Config and public activation/notification journeys."""
import asyncio
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

CONFIGS=[{},dict(clientInspectTimeoutMs=1),dict(clientInspectTimeoutMs=2147483647),dict(clientInspectTimeoutMs=0),
 dict(clientInspectTimeoutMs=-1),dict(clientInspectTimeoutMs=1.5),dict(clientInspectTimeoutMs=2147483648),
 dict(clientInspectTimeoutMs=True),dict(clientInspectTimeoutMs='10'),dict(clientInspectTimeoutMs=None),
 dict(clientInspectTimeoutMs='NaN'),dict(clientInspectTimeoutMs='Infinity'),dict(vmTimeoutMs=1.5),
 dict(vmTimeoutMs=0),dict(vmTimeoutMs=True),dict(vmTimeoutMs='Infinity'),dict(vmTimeoutMs=None),
 dict(vmTimeoutMs=23,clientInspectTimeoutMs=17),dict(extra='kept')]
MODES=['approved','rejected','failure','failure-unapproved','guard','render','handler','panel','foreign-agent']
HOST="def plugin(ctx):\n    def fail(message):\n        def invoke(args):\n            error = ValueError(message)\n            error.stack = 'fixture stack'\n            raise error\n        return invoke\n    harness.handle('fail', fail('handler failed'))\n    harness.handle('a\\x00b', fail('c'))\n    harness.handle('a', fail('b\\x00c'))\n"


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(dict(configs=CONFIGS,modes=MODES)),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis import Context
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.extensions.host_runner_current import CurrentDynamicCordisRunner
    rows=[]
    for value in CONFIGS:
        config={key:float(value) if value in ('NaN','Infinity') else value for key,value in value.items()}
        try:row=dict(value=CurrentDynamicCordisRunner.Config(config))
        except Exception as error:row=dict(error=str(error))
        rows.append(dict(stage='config',**row))
    for mode in MODES:
        ctx=Context();events=[];messages=[];injected=[];results=[]
        def message(value):return {key:value[key] for key in ('content','source')}
        agent=NS(id='agent',steer=lambda value:messages.append(message(value)),inject=lambda value:injected.append(message(value)))
        agent.ctx=ctx
        try:
            for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin]:await ctx.plugin(plugin)
            ctx.provide('agents',{agent.id:agent})
            await ctx.plugin(CurrentDynamicCordisRunner,dict(clientInspectTimeoutMs=37))
            runner=ctx.get('dynamicCordisRunner')
            for name in ['cordis/request-run','cordis/request-run-resolved','cordis/dynamic-package','cordis/dynamic-retract']:
                ctx.on(name,lambda value,name=name:events.append([name,copy.deepcopy(value)]))
            request=dict(sessionId=agent.id,plugin=dict(kind='new',idPrefix='probe'),name='First',purpose='fixture',code=dict(client='return () => {}'))
            if mode=='handler':request['code']['host']=HOST
            definition=runner.define(request);pid=definition['pluginId'];package=definition['packageId']
            results.append(definition)
            results.append(await runner.run(agent,pid,package,'run'))
            rid=events[-1][1]['requestId']
            if mode in ['rejected','failure-unapproved']:
                resolution=dict(ok=False,reason='rejected') if mode=='rejected' else dict(ok=False,reason='client-half-failed',message='client failed',stack='fixture stack')
                results.append(await runner.resolveRequestRun(rid,resolution))
            else:
                started=await runner.runHostHalf(agent,pid,package,'run',rid,True);results.append(started)
                results.append(await runner.resolveRequestRun(rid,dict(ok=True,pluginRunId=started['pluginRunId'])))
                if mode=='failure':
                    updated=runner.define(dict(request,plugin=dict(kind='existing',pluginId=pid),name='Second'));results.append(updated)
                    results.append(await runner.run(agent,pid,updated['packageId'],'update'))
                    rid=events[-1][1]['requestId']
                    results.append(await runner.resolveRequestRun(rid,dict(ok=False,reason='client-half-failed',message='client failed',stack='fixture stack')))
                elif mode=='guard':
                    for _ in range(2):results.append(await runner.reportClientGuardFailure(agent,pid,started['pluginRunId'],dict(message='guard failed',stack='fixture stack')))
                elif mode=='render':
                    for i in range(2):results.append(await runner.reportRenderFailure(agent,pid,started['pluginRunId'],dict(message='render failed '+str(i),stack='fixture stack',slot='main',abdicated=bool(i))))
                elif mode=='handler':
                    for method in ['fail','fail','a\0b','a']:results.append(await runner.invoke(pid,started['pluginRunId'],method,{}))
                elif mode=='panel':
                    results.append(await runner.stopFromPanel(agent,pid));results.append(await runner.undefineFromPanel(agent,pid))
                elif mode=='foreign-agent':
                    results.append(await runner.stopFromPanel(NS(id='foreign'),pid))
                    runner.inject_user_context(NS(id='agent',inject=lambda _:injected.append('wrong')), 'do not inject')
            rows.append(dict(stage=mode,results=results,events=events,messages=messages,injected=injected,inventory=runner.inventory(),timeout=runner.inspect_registry.clientQueryTimeoutMs))
        finally:await ctx.fiber.dispose()
    def encode(value):
        if isinstance(value,list):return [encode(child) for child in value]
        if isinstance(value,dict):return {key:encode(child) for key,child in value.items()}
        if type(value) is float and not math.isfinite(value):return dict(number='NaN' if math.isnan(value) else 'Infinity' if value>0 else '-Infinity')
        return value
    return encode(rows)


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_host_runner.mts',prepare=prepare,
        scope='Current actual runner Config validation and public activation/approval/notification journeys with current Client inspect deadline wiring. Host handler executes real JavaScript Source/Python Native dynamic bodies with the same explicit error stack; no arbitrary evaluator equivalence is inferred.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/extensions/host_runner_current.py',ROOT/'dsh/extensions/inspect_registry_current.py'])
