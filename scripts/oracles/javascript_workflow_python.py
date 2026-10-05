import asyncio
import copy
import json
import sys
import argparse
import hashlib
from pathlib import Path
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--cases', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.subagent.runtime import SubagentRuntime
from dsh.workflow.workflow_service import WorkflowEngine




async def observe(scenario):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    await ctx.plugin(SubagentRuntime)
    events, requests, children = [], [], []
    provider_entered, agent_entered, provider_released, child_disposed = [asyncio.Event() for _ in range(4)]
    parent = SimpleNamespace(id='parent', options={}, ctx=ctx)
    run = None
    class Provider:
        name, inheritsParentContext = 'spawn', False
        capabilities = dict(agentOptions=True, outputSchema=True, depthLimit=False, toolFilter=False, persona=False)
        async def start(self, request):
            recorded = dict(route='spawn', prompt=request['prompt'], parentSame=request['parent'] is parent,
                            abortedAtStart=request['signal'].aborted)
            for key in ('outputSchema', 'agentOptions'):
                if key in request:
                    recorded[key] = request[key]
            requests.append(recorded)
            provider_entered.set()
            if scenario.get('death') == 'pending-start':
                await provider_released.wait()
            if scenario.get('cancelAtStart'):
                run.cancel('active child cancellation')
            prompt = request['prompt'][0]['text']
            result = dict(output=[dict(type='text', text=prompt)], stopReason='completed')
            if prompt == 'failed':
                result = dict(output=[], stopReason='error')
            elif prompt == 'blocks':
                result['output'] = [dict(type='text', text='first'), dict(type='image', data='ignored'), dict(type='text', text='second')]
            if 'outputSchema' in request and prompt != 'unhonored':
                result['structured'] = dict(answer=42)
            child = SimpleNamespace(id='child-' + str(len(requests)), disposed=0, result=asyncio.get_event_loop().create_future())
            if scenario.get('death') != 'published-child':
                child.result.set_result(result)
            async def dispose():
                child.disposed += 1
                child_disposed.set()
            child.dispose = dispose
            children.append(child)
            return child
    ctx.get('subagents').registerProvider(Provider())
    await ctx.plugin(WorkflowEngine, dict(maxConcurrentAgents=scenario.get('concurrent', 2),
        maxTotalAgents=scenario.get('total', 10), maxItemsPerCall=scenario.get('items', 30),
        syncTimeoutMs=200, disposeGraceMs=200))
    late = asyncio.Event()
    for name in ('start', 'phase', 'log', 'agent-start', 'agent-end', 'end'):
        def observed(info, value=None, name=name):
            message = dict(type=name)
            if name in ('agent-start', 'agent-end'):
                message['info'] = copy.deepcopy(value)
            elif name == 'end':
                message['outcome'] = copy.deepcopy(value)
            elif name == 'phase':
                message['title'] = value
            elif name == 'log':
                message['message'] = value
            events.append(message)
            if name == 'agent-start':
                agent_entered.set()
            if (scenario['name'] == 'dropped-child-after-result' and name == 'agent-end'
                    or scenario['name'] == 'dropped-child-continuation' and name == 'log'):
                late.set()
        ctx.on('workflow/' + name, observed)
    signal = AbortController()
    if scenario.get('cancelBeforeGo'):
        signal.abort()
    try:
        run = ctx.get('workflowEngine').start(dict(script=scenario['body'],
            meta=dict(name=scenario['name'], description='actual Source host RPC'), parent=parent,
            args=dict(nested=dict(value=2)), signal=signal.signal))
        if scenario.get('death') and scenario['death'] != 'settled':
            await asyncio.wait_for((agent_entered if scenario['death'] == 'published-child' else provider_entered).wait(), 5)
            if scenario.get('cancelBeforeDeath'):
                run.cancel('')
            run._worker.process.kill()
        result = await asyncio.wait_for(asyncio.shield(run.result), 5)
        alive = run._worker is not None and run._worker.process.returncode is None
        if scenario.get('death') == 'pending-start':
            provider_released.set()
        if scenario.get('death') and scenario['death'] != 'settled':
            await asyncio.wait_for(child_disposed.wait(), 5)
        if scenario.get('death') == 'settled':
            run._worker.process.kill()
            await asyncio.wait_for(asyncio.shield(run._worker.closed), 5)
        if scenario.get('waitDisposals'):
            await asyncio.wait_for(late.wait(), 5)
        await asyncio.wait_for(run.dispose(), 5)
        report = dict(name=scenario['name'], result=result, events=events, requests=requests, aliveAfterResult=alive,
                      disposed=[child.disposed for child in children], signalAborted=run.controller.signal.aborted)
        if scenario.get('death'):
            report.update(exitCode=run._worker.process.returncode, firstResultRetained=result is await asyncio.shield(run.result))
        return report
    finally:
        provider_released.set()
        await ctx.fiber.dispose()


async def main():
    cases = json.loads(options.cases.read_text(encoding='utf-8'))
    observations = [await observe(scenario) for scenario in cases]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if not path or not (name == 'dsh' or name.startswith('dsh.')):
            continue
        selected = Path(path).resolve()
        relative = selected.relative_to(ROOT).as_posix()
        modules[relative] = hashlib.sha256(selected.read_bytes()).hexdigest()
    assets = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for directory in ('dsh/javascript/bin', 'dsh/javascript/workflow')
              for path in sorted((ROOT / directory).iterdir()) if path.is_file()}
    report = dict(root=str(ROOT), python=sys.version, executable=sys.executable,
                  modules=modules, assets=assets, observations=observations)
    options.output.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + '\n', encoding='utf-8')


asyncio.run(main())
