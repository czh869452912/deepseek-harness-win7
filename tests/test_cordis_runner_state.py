"""Pinned runner journeys and actual canonical Remote/activation lifetimes."""
from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from canonical_web_fixture import web_context, close_web_context
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.core.abort import AbortController
from dsh.extensions.host_runner import DynamicCordisRunner
from dsh.typert.dispatch import RemoteDispatcher
from scripts.cordis_runner_oracle import classify, collision_projection, native_projection, source_fixture_matches
from scripts.oracles.cordis_runner_python import observe

ROOT = Path(__file__).resolve().parents[1]
SPECS = json.loads((ROOT / 'scripts/oracles/cordis-runner-cases.json').read_text(encoding='utf-8'))
FIXTURE = json.loads((ROOT / 'tests/fixtures/cordis-runner-source-observations.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec,source', list(zip(SPECS, FIXTURE['observations'])), ids=[spec['mode'] for spec in SPECS])
async def test_actual_runner_source_journey(spec, source):
    expected = collision_projection(source) if spec['mode'] == 'runtime-error-nul-collision' else native_projection(source)
    assert await observe(spec) == expected


@pytest.mark.asyncio
async def test_same_approval_request_attaches_to_existing_run_for_both_approval_modes():
    spec = next(row for row in SPECS if row['mode'] == 'approval-repeat-attach')
    actual = await observe(spec)
    rows = actual['rows']
    for first, repeated in [(3, 4), (9, 10)]:
        assert rows[first]['value']['startedHere'] is True
        assert rows[repeated]['value']['startedHere'] is False
        assert rows[first]['value']['pluginRunId'] == rows[repeated]['value']['pluginRunId']
        assert rows[repeated]['inventory'][0]['latestRun']['status'] == 'client-pending'
    assert rows[1]['value']['status'] == 'awaiting-approval'
    assert rows[7]['value']['status'] == 'starting'
    assert not rows[6]['value']['ok']  # The resolved request no longer authorizes an attachment.


def test_runner_source_fixture_is_bound_to_actual_pinned_inputs():
    assert FIXTURE['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert [row['mode'] for row in FIXTURE['observations']] == [spec['mode'] for spec in SPECS]
    for path, digest in FIXTURE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


@pytest.mark.parametrize('damage', ['missing-stack', 'source-line', 'exception-type', 'extra-frame'])
def test_python_apply_projection_requires_the_complete_captured_traceback(damage):
    source = next(row for row in FIXTURE['observations'] if row['mode'] == 'actual-host-apply-failure-and-retry')
    native = native_projection(source)
    assert classify(source, native) == 'matched-with-Python-lifecycle-stack'
    failure = native['rows'][1]['value']
    if damage == 'missing-stack':
        del failure['stack']
    elif damage == 'source-line':
        failure['stack'] = failure['stack'].replace('File "<cordis-host>", line 2', 'File "<cordis-host>", line 3')
    elif damage == 'exception-type':
        failure['stack'] = failure['stack'].replace('ValueError: fixture apply failure', 'TypeError: fixture apply failure')
    else:
        failure['stack'] += '  File "foreign.py", line 1, in unexpected\n'
    assert classify(source, native) == 'different'


def captured_async_source_fixture():
    actual = copy.deepcopy(FIXTURE)
    rows = actual['observations'][13]['rows']
    stack = (ROOT / 'tests/fixtures/cordis-runner-source-async-stack.txt').read_text(encoding='utf-8').rstrip('\n')
    rows[1]['value']['stack'] = stack
    for index in (1, 2, 3, 4):
        rows[index]['inventory'][0]['latestRun']['error']['stack'] = stack
    rows[3]['value']['latestRun']['error']['stack'] = stack
    return actual


def test_source_fixture_accepts_both_exact_captured_scheduling_layouts():
    before = copy.deepcopy(FIXTURE)
    assert source_fixture_matches(FIXTURE, before)
    assert source_fixture_matches(FIXTURE, captured_async_source_fixture())
    assert FIXTURE == before


@pytest.mark.parametrize('damage', ['source-line', 'source-column', 'node-frame', 'unknown-frame',
    'one-stack', 'message', 'operation', 'input', 'target', 'other-journey', 'missing-stack'])
def test_source_scheduling_layout_does_not_accept_any_other_drift(damage):
    actual = captured_async_source_fixture()
    row = actual['observations'][13]['rows'][1]
    if damage in ('source-line', 'source-column', 'node-frame', 'unknown-frame', 'one-stack'):
        stack = row['value']['stack']
        if damage == 'source-line':
            stack = stack.replace('lifecycle.ts:28:27', 'lifecycle.ts:29:27')
        elif damage == 'source-column':
            stack = stack.replace('lifecycle.ts:28:27', 'lifecycle.ts:28:28')
        elif damage == 'node-frame':
            stack = stack.replace('task_queues:64:5', 'task_queues:65:5')
        elif damage == 'unknown-frame':
            stack += '\n    at unknown (node:internal/foreign:1:1)'
        else:
            stack = FIXTURE['observations'][13]['rows'][1]['value']['stack']
        row['value']['stack'] = stack
    elif damage == 'message':
        row['value']['message'] = 'foreign'
    elif damage == 'operation':
        row['op'] = 'foreign'
    elif damage == 'input':
        actual['source_sha256']['scripts/oracles/cordis-runner.spec.ts'] = '0' * 64
    elif damage == 'target':
        actual['target_upstream'] = '0' * 40
    elif damage == 'other-journey':
        actual['observations'][0]['rows'][0]['value']['purpose'] = 'foreign'
    else:
        del row['value']['stack']
    assert not source_fixture_matches(FIXTURE, actual)


def test_collision_exception_accepts_only_exact_added_notification():
    source = next(row for row in FIXTURE['observations'] if row['mode'] == 'runtime-error-nul-collision')
    corrected = collision_projection(source)
    assert classify(source, corrected) == 'reviewed-upstream-bug/CORDIS-RUNTIME-001-with-Python-guidance'
    changed = copy.deepcopy(corrected)
    changed['rows'][3]['value']['message'] = 'wrong'
    assert classify(source, changed) == 'different'
    changed = copy.deepcopy(corrected)
    changed['rows'][4]['steer'] = changed['rows'][3]['steer']
    assert classify(source, changed) == 'different'
    changed = copy.deepcopy(corrected)
    changed['rows'][3]['steer'][0]['content'][0]['text'] += 'extra'
    assert classify(source, changed) == 'different'


@pytest.mark.asyncio
async def test_cancelled_activation_waiter_does_not_leave_starting_or_cancel_shared_host():
    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner, entered, release = ctx.get('dynamicCordisRunner'), asyncio.Event(), asyncio.Event()
    ctx.provide('runnerGate', NS(entered=entered, release=release))
    owner = NS(id='owner')
    source = "async def plugin(ctx):\n    gate = ctx.get('runnerGate')\n    gate.entered.set()\n    await gate.release.wait()\n    ctx.provide('lateActivation', 'ready')\n"
    defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Delayed', purpose='real async apply', code=dict(host=source)))
    pending = asyncio.create_task(runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        activation = runner.starting[defined['pluginId']]
        assert (await runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))['reason'] == 'transition-in-flight'
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not activation.cancelled()
        release.set()
        assert (await asyncio.wait_for(asyncio.shield(activation), 1))['ok']
        await asyncio.sleep(0)
        assert not runner.starting
        assert runner.inventory()[0]['currentPackageId'] == defined['packageId']
        assert ctx.get('lateActivation') == 'ready'
        assert (await runner.stop(owner, defined['pluginId'])) == dict(ok=True)
        assert ctx.get('lateActivation') is None
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_remote_binds_original_failure_fields_and_activation_events(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    stream, controller = None, AbortController()
    try:
        await ctx.get('sessionController').create(dict(sessionId='runner-owner', cwd=str(tmp_path), agentPreset='minimal'))
        owner = ctx.get('agents').get('runner-owner')
        runner = ctx.get('dynamicCordisRunner')
        stream = await ctx.get('typertGateway').open_wire_stream('$events', dict(args={}), controller.signal)
        assert (await stream.__anext__())['type'] == 'ready'
        gateway = RemoteDispatcher(ctx)
        events = []
        for name in ('cordis/request-run', 'cordis/request-run-resolved', 'cordis/dynamic-package', 'cordis/dynamic-retract'):
            ctx.on(name, lambda payload, name=name: events.append([name, payload]))
        async def remote(method, **args):
            return await gateway.invoke(dict(namespace='dynamicCordisRunner', method=method, args=args))
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='panel'), name='Panel', purpose='actual Remote', code=dict(client='return () => {}')))
        pid, package = defined['pluginId'], defined['packageId']
        assert 'nextPackageId' not in runner.inventory()[0]
        request = await runner.run(owner, pid, package, 'run')
        rid = events[-1][1]['requestId']
        half = await remote('runHostHalf', agentId=owner.id, pluginId=pid, packageId=package, mode='run', requestId=rid, approveFutureVersions=False)
        assert half['pluginRunId'] == request['pluginRunId']
        assert (await remote('getClientCode', agentId=owner.id, pluginId=pid, pluginRunId=half['pluginRunId']))['code'] == 'return () => {}'
        assert await remote('resolveRequestRun', requestId=rid, resolution=dict(ok=True, pluginRunId=half['pluginRunId'])) == dict(accepted=True)
        assert await remote('reportClientGuardFailure', agentId=owner.id, pluginId=pid, pluginRunId=half['pluginRunId'], failure=dict(message='guard failed')) is None
        assert await remote('reportRenderFailure', agentId=owner.id, pluginId=pid, pluginRunId=half['pluginRunId'], failure=dict(slot='panel', message='render failed', abdicated=True)) is None
        assert runner.inventory()[0]['latestRun']['error']['phase'] == 'client-render'
        assert await remote('stopFromPanel', agentId=owner.id, pluginId=pid) == dict(ok=True)
        assert [name for name, _ in events] == ['cordis/request-run', 'cordis/dynamic-package', 'cordis/request-run-resolved', 'cordis/dynamic-retract']
        assert events[2][1] == dict(requestId=rid, outcome='approved')
        forwarded = []
        while len(forwarded) < 4:
            frame = await asyncio.wait_for(stream.__anext__(), 1)
            if frame['type'] == 'emit' and frame['event'].startswith('cordis/'):
                forwarded.append([frame['event'], frame['args'][0]])
        assert forwarded == events
        assert await remote('undefineFromPanel', agentId=owner.id, pluginId=pid) == dict(ok=True, wasRunning=False)
    finally:
        controller.abort()
        if stream is not None:
            await stream.aclose()
        await close_web_context(ctx)
