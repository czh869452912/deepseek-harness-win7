"""Pinned runner journeys and actual canonical Remote/activation lifetimes."""
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
from scripts.cordis_runner_oracle import classify, collision_projection, native_projection
from scripts.oracles.cordis_runner_python import observe

ROOT = Path(__file__).resolve().parents[1]
SPECS = json.loads((ROOT / 'scripts/oracles/cordis-runner-cases.json').read_text(encoding='utf-8'))
FIXTURE = json.loads((ROOT / 'tests/fixtures/cordis-runner-source-observations.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec,source', list(zip(SPECS, FIXTURE['observations'])), ids=[spec['mode'] for spec in SPECS])
async def test_actual_runner_source_journey(spec, source):
    expected = collision_projection(source) if spec['mode'] == 'runtime-error-nul-collision' else native_projection(source)
    assert await observe(spec) == expected


def test_runner_source_fixture_is_bound_to_actual_pinned_inputs():
    assert FIXTURE['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert [row['mode'] for row in FIXTURE['observations']] == [spec['mode'] for spec in SPECS]
    for path, digest in FIXTURE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


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
