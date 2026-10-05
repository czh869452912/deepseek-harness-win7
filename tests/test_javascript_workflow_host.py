import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.subagent.runtime import SubagentRuntime
from dsh.workflow.workflow_service import WorkflowEngine, WorkflowError

import os
import subprocess
import pytest


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/javascript-workflow/cases.json').read_text(encoding='utf-8'))
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')


@pytest.fixture(scope='module')
def source_host_observations(tmp_path_factory):
    output = tmp_path_factory.mktemp('js-host-source') / 'observations'
    completed = subprocess.run(['node', str(ROOT / 'scripts/oracles/javascript_workflow_host_source.mjs'), str(output)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=120)
    (output.parent / 'source.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads((output / 'source.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', CASES, ids=[scenario['name'] for scenario in CASES])
async def test_workflow_engine_actual_source_host_events_and_children(scenario, source_host_observations, tmp_path):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    await ctx.plugin(SubagentRuntime)
    events, requests, children = [], [], []
    late = asyncio.Event()
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
            child.result.set_result(result)
            async def dispose():
                child.disposed += 1
            child.dispose = dispose
            children.append(child)
            return child
    ctx.get('subagents').registerProvider(Provider())
    await ctx.plugin(WorkflowEngine, dict(maxConcurrentAgents=scenario.get('concurrent', 2),
        maxTotalAgents=scenario.get('total', 10), maxItemsPerCall=scenario.get('items', 30),
        syncTimeoutMs=200, disposeGraceMs=200))
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
        assert not ctx.get('workflowEngine')._native_programs
        result = await asyncio.wait_for(asyncio.shield(run.result), 5)
        alive = run._worker is not None and run._worker.process.returncode is None
        if scenario.get('waitDisposals'):
            await asyncio.wait_for(late.wait(), 5)
        await asyncio.wait_for(run.dispose(), 5)
        native = dict(name=scenario['name'], result=result, events=events, requests=requests, aliveAfterResult=alive,
                      disposed=[child.disposed for child in children], signalAborted=run.controller.signal.aborted)
        (tmp_path / 'native.json').write_text(json.dumps(native, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        source = next(record for record in source_host_observations['observations'] if record['name'] == scenario['name'])
        assert native == source
        assert run._worker.closed.done()
        assert not ctx.get('workflowEngine')._active_runs
    finally:
        await ctx.fiber.dispose()
