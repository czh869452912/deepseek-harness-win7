import asyncio
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.cordis.context import Context
from dsh.javascript import runtime as implementation
from dsh.javascript.runtime import JavaScriptRuntime, JavaScriptRuntimeError, workflow_bootstrap


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/javascript-workflow/cases.json').read_text(encoding='utf-8'))
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')


@pytest.fixture(scope='module')
def source_observations(tmp_path_factory):
    output = tmp_path_factory.mktemp('js-workflow-source') / 'observations'
    completed = subprocess.run(['node', str(ROOT / 'scripts/oracles/javascript_workflow_source.mjs'), str(output)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=120)
    (output.parent / 'source.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads((output / 'source.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', CASES, ids=[scenario['name'] for scenario in CASES])
async def test_actual_source_session_child_rpc_and_retained_process(scenario, source_observations, tmp_path):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    initial = dict(body=scenario['body'], meta=dict(name=scenario['name'], description='actual Source worker RPC'),
        args=dict(nested=dict(value=2)), limits=dict(maxConcurrentAgents=scenario.get('concurrent', 2),
            maxTotalAgents=scenario.get('total', 10), maxItemsPerCall=scenario.get('items', 30), syncTimeoutMs=200))
    original = copy.deepcopy(initial)
    frames, worker = [dict(type='ready')], None
    boundary = asyncio.Event()
    async def observe(message):
        message = dict(message)
        if message['type'] == 'terminal':
            message['type'] = 'result'
        frames.append(message)
        if message['type'] == 'child-start':
            if scenario.get('cancelAtStart'):
                await worker.cancel('active child cancellation')
            await worker.send(dict(type='child-started', callId=message['callId'], childId='child-' + str(message['callId'])))
            prompt = message['request']['prompt']
            result = dict(output=[dict(type='text', text=prompt)], stopReason='completed')
            if prompt == 'failed':
                result = dict(output=[], stopReason='error')
            elif prompt == 'blocks':
                result['output'] = [dict(type='text', text='first'), dict(type='image', data='ignored'), dict(type='text', text='second')]
            if 'schema' in message['request'] and prompt != 'unhonored':
                result['structured'] = dict(answer=42)
            await worker.send(dict(type='child-settled', callId=message['callId'], result=result))
        elif message['type'] == 'child-dispose':
            await worker.send(dict(type='child-disposed', callId=message['callId']))
        if (not scenario.get('waitDisposals') and message['type'] == 'result'
                or scenario['name'] == 'dropped-child-after-result' and message['type'] == 'agent-end'
                or scenario['name'] == 'dropped-child-continuation' and message['type'] == 'log'):
            boundary.set()
    try:
        worker = await ctx.get('jsRuntime').open_workflow(initial, observe)
        if scenario.get('cancelBeforeGo'):
            await worker.cancel('already aborted')
        else:
            await worker.send(dict(type='go'))
        await asyncio.wait_for(boundary.wait(), 5)
        await asyncio.wait_for(asyncio.shield(worker.result), 5)
        native = dict(name=scenario['name'], frames=frames, aliveAfterResult=worker.process.returncode is None)
        source = next(record for record in source_observations['observations'] if record['name'] == scenario['name'])
        (tmp_path / 'native.json').write_text(json.dumps(native, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        assert native == source
        if scenario['name'] == 'signed-zero':
            assert math.copysign(1, native['frames'][-1]['result']['value']['zero']) == -1
            assert math.copysign(1, source['frames'][-1]['result']['value']['zero']) == -1
        assert initial == original
        assert not worker.closed.done()
        assert worker.dispose() is worker.dispose()
        await asyncio.wait_for(worker.dispose(), 5)
        assert worker.closed.done() and worker.process.returncode is not None
        assert worker.failure is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize('name', ['source.js', 'driver.js', 'workflow.json', 'build-provenance.json', 'SOURCE-LICENSE'])
def test_corrupt_source_session_resources_are_refused(tmp_path, monkeypatch, name):
    copied = tmp_path / 'workflow'
    shutil.copytree(str(implementation.WORKFLOW_ROOT), str(copied))
    with (copied / name).open('ab') as stream:
        stream.write(b'corrupt')
    monkeypatch.setattr(implementation, 'WORKFLOW_ROOT', copied)
    with pytest.raises(JavaScriptRuntimeError, match='differ'):
        workflow_bootstrap()


@pytest.mark.asyncio
async def test_owner_unload_physically_terminates_unsettled_source_session():
    ctx = Context()
    fiber = await ctx.plugin(JavaScriptRuntime)
    worker = await ctx.get('jsRuntime').open_workflow(dict(body='await Promise.resolve();for(;;){}',
        meta=dict(name='post-await-cpu', description='owner termination'), args=None,
        limits=dict(maxConcurrentAgents=1, maxTotalAgents=1, maxItemsPerCall=1, syncTimeoutMs=20)), grace_ms=20)
    await worker.send(dict(type='go'))
    try:
        await asyncio.wait_for(fiber.dispose(), 5)
        assert worker.closed.done() and worker.process.returncode is not None
        assert ctx.get('jsRuntime') is None
    finally:
        await ctx.fiber.dispose()
