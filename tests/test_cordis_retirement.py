"""Source races, cancellation ownership and actual canonical runner unload."""
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
from dsh.extensions.host_runner import DynamicCordisRunner
from dsh.typert.dispatch import RemoteDispatcher
from scripts.cordis_retirement_oracle import classify, corrected_observation, BUG_HASHES
from scripts.oracles.cordis_retirement_python import observe, HOST

ROOT = Path(__file__).resolve().parents[1]
SPECS = json.loads((ROOT / 'scripts/oracles/cordis-retirement-cases.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec', SPECS, ids=[spec['mode'] for spec in SPECS])
async def test_actual_source_retirement(spec):
    fixture = json.loads((ROOT / 'tests/fixtures/cordis-retirement-source-observations.json').read_text(encoding='utf-8'))
    source = next(row for row in fixture['observations'] if row['mode'] == spec['mode'])
    native = await observe(spec)
    expected = corrected_observation(source) if source['mode'] in BUG_HASHES else source
    assert native == expected


def test_source_binding_and_exact_bug_exception():
    fixture = json.loads((ROOT / 'tests/fixtures/cordis-retirement-source-observations.json').read_text(encoding='utf-8'))
    assert fixture['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert [row['mode'] for row in fixture['observations']] == [spec['mode'] for spec in SPECS]
    for path, digest in fixture['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path
    for source in fixture['observations']:
        if source['mode'] not in BUG_HASHES:
            continue
        native = corrected_observation(source)
        assert classify(source, native) == 'reviewed-upstream-bug/CORDIS-LIFECYCLE-001'
        for key in ('before', 'during', 'started', 'ended', 'after'):
            bad = copy.deepcopy(native)
            bad[key]['extra'] = True
            assert classify(source, bad) == 'different'
        bad = copy.deepcopy(source)
        bad['after']['values'][2] = None
        assert classify(bad, native) == 'different'


async def starting_runner(ctx):
    entered, release = asyncio.Event(), asyncio.Event()
    async def wait():
        entered.set()
        await release.wait()
    ctx.provide('runnerGate', NS(wait=wait))
    runner, owner = ctx.get('dynamicCordisRunner'), NS(id='owner')
    defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Probe', purpose='retirement', code=dict(host=HOST)))
    task = asyncio.create_task(runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))
    await asyncio.wait_for(entered.wait(), 1)
    return runner, owner, defined, task, release


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['stop', 'undefine', 'close'])
async def test_cancelled_retirement_waiter_still_owns_cleanup(action):
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner, owner, defined, activation, release = await starting_runner(ctx)
    ending = asyncio.create_task(runner.close() if action == 'close' else getattr(runner, action)(owner, defined['pluginId']))
    try:
        await asyncio.sleep(.01)
        assert not ending.done()
        ending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await ending
        assert not activation.done()
        assert (await runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))['reason'] == 'transition-in-flight'
        release.set()
        assert (await asyncio.wait_for(activation, 1))['reason'] == 'cancelled'
        if action == 'close':
            await asyncio.wait_for(runner.close(), 1)
        else:
            await asyncio.wait_for(asyncio.shield(runner._ending[defined['pluginId']]['task']), 1)
        assert not runner.starting and not runner._transitions and not runner._ending
        assert ctx.get('probeValue') is None and ctx.get('probeLate') is None
        assert not runner.inventory() if action != 'stop' else runner.inventory()[0]['latestRun']['status'] == 'stopped'
    finally:
        release.set()
        await asyncio.gather(activation, ending, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_concurrent_remove_escalates_owned_stop_and_permits_fresh_definition():
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner, owner, defined, activation, release = await starting_runner(ctx)
    stop = asyncio.create_task(runner.stop(owner, defined['pluginId']))
    await asyncio.sleep(.01)
    remove = asyncio.create_task(runner.undefine(owner, defined['pluginId']))
    try:
        await asyncio.sleep(.01)
        assert len(runner._ending) == 1
        release.set()
        assert await asyncio.wait_for(stop, 1) == dict(ok=True)
        assert await asyncio.wait_for(remove, 1) == dict(ok=True, wasRunning=False)
        assert (await activation)['reason'] == 'cancelled'
        assert runner.inventory() == []
        fresh = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Fresh', purpose='after removal', code=dict(host="def plugin(ctx):\n    ctx.provide('probeFresh', 'ready')\n")))
        assert (await runner.run(owner, fresh['pluginId'], fresh['packageId'], 'run'))['ok']
        assert ctx.get('probeFresh') == 'ready'
        assert await runner.stop(owner, fresh['pluginId']) == dict(ok=True)
        assert ctx.get('probeFresh') is None
    finally:
        release.set()
        await asyncio.gather(activation, stop, remove, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_runner_fiber_unload_joins_incomplete_apply_without_late_publication():
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    runner_fiber = ctx.plugin(DynamicCordisRunner)
    await runner_fiber
    events = []
    ctx.on('cordis/dynamic-package', lambda value: events.append(value))
    runner, owner, defined, activation, release = await starting_runner(ctx)
    unload = asyncio.create_task(runner_fiber.dispose())
    try:
        await asyncio.sleep(.01)
        assert not unload.done()
        release.set()
        assert (await asyncio.wait_for(activation, 1))['reason'] == 'cancelled'
        await asyncio.wait_for(unload, 1)
        assert ctx.get('dynamicCordisRunner') is None
        assert ctx.get('probeValue') is None and ctx.get('probeLate') is None
        assert runner.inventory() == [] and not runner.starting and not runner._ending
        assert events == []
        with pytest.raises(ValueError, match='closed'):
            runner.define({})
    finally:
        release.set()
        await asyncio.gather(activation, unload, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_remote_delete_retires_real_host_activation(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    activation, ending, release = None, None, None
    try:
        await ctx.get('sessionController').create(dict(sessionId='owner', cwd=str(tmp_path), agentPreset='minimal'))
        runner, owner, defined, activation, release = await starting_runner(ctx)
        dispatcher = RemoteDispatcher(ctx)
        ending = asyncio.create_task(dispatcher.invoke(dict(namespace='dynamicCordisRunner', method='undefineFromPanel',
            args=dict(agentId=owner.id, pluginId=defined['pluginId']))))
        await asyncio.sleep(.01)
        assert not ending.done()
        release.set()
        assert (await asyncio.wait_for(activation, 1))['reason'] == 'cancelled'
        assert await asyncio.wait_for(ending, 1) == dict(ok=True, wasRunning=False)
        assert runner.inventory() == []
        assert ctx.get('probeValue') is None and ctx.get('probeLate') is None
    finally:
        if release is not None:
            release.set()
        await asyncio.gather(*(task for task in (activation, ending) if task is not None), return_exceptions=True)
        await close_web_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['stop', 'undefine'])
async def test_retirement_waits_for_real_tool_unwind_and_async_cleanup(action):
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    entered, release = asyncio.Event(), asyncio.Event()
    cleaning, finish = asyncio.Event(), asyncio.Event()
    cleaned = []
    async def wait():
        entered.set()
        await release.wait()
    ctx.provide('runnerGate', NS(wait=wait, cleaning=cleaning, finish=finish, cleaned=cleaned))
    source = "async def plugin(ctx):\n    gate = ctx.get('runnerGate')\n    tool = harness.defineTool({'name': 'retiring_probe', 'description': 'Probe', 'parameters': {}, 'output': {'schema': {'type': 'json'}, 'render': lambda args, value: []}, 'execute': lambda args, execution: {}})\n    ctx.tools.register(tool)\n    async def cleanup():\n        gate.cleaning.set()\n        await gate.finish.wait()\n        gate.cleaned.append('done')\n    ctx.effect(lambda: cleanup)\n    await gate.wait()\nplugin.inject = ['tools']\n"
    runner, owner = ctx.get('dynamicCordisRunner'), NS(id='owner')
    defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Probe', purpose='cleanup', code=dict(host=source)))
    activation = asyncio.create_task(runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))
    ending = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert ctx.get('tools').get('retiring_probe') is not None
        ending = asyncio.create_task(getattr(runner, action)(owner, defined['pluginId']))
        await asyncio.sleep(.01)
        release.set()
        await asyncio.wait_for(cleaning.wait(), 1)
        assert not ending.done() and not activation.done() and cleaned == []
        finish.set()
        assert (await asyncio.wait_for(activation, 1))['reason'] == 'cancelled'
        assert (await asyncio.wait_for(ending, 1))['ok']
        assert cleaned == ['done']
        assert ctx.get('tools').get('retiring_probe') is None
        assert not runner._ending and not runner.starting
    finally:
        release.set()
        finish.set()
        await asyncio.gather(*(task for task in (activation, ending) if task is not None), return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_close_cancels_pending_browser_request_and_rejects_late_reply():
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner, owner, events = ctx.get('dynamicCordisRunner'), NS(id='owner'), []
    ctx.on('cordis/request-run-resolved', lambda value: events.append(value))
    try:
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Panel', purpose='shutdown', code=dict(client='return () => {}')))
        assert (await runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))['status'] == 'awaiting-approval'
        rid = runner.pending_for(defined['pluginId'])
        await asyncio.gather(runner.close(), runner.close())
        assert events == [dict(requestId=rid, outcome='cancelled')]
        assert not runner.pending and runner.inventory() == []
        assert await runner.resolveRequestRun(rid, dict(ok=False, reason='rejected')) == dict(accepted=False)
        assert (await runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))['reason'] == 'plugin-missing'
        with pytest.raises(ValueError, match='closed'):
            runner.define({})
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_stop_during_previous_version_cleanup_prevents_new_apply():
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    cleaning, finish, entered = asyncio.Event(), asyncio.Event(), []
    ctx.provide('runnerGate', NS(cleaning=cleaning, finish=finish, entered=entered))
    runner, owner = ctx.get('dynamicCordisRunner'), NS(id='owner')
    old = "def plugin(ctx):\n    gate = ctx.get('runnerGate')\n    ctx.provide('previousVersion', 'ready')\n    async def cleanup():\n        gate.cleaning.set()\n        await gate.finish.wait()\n    ctx.effect(lambda: cleanup)\n"
    defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Old', purpose='update', code=dict(host=old)))
    assert (await runner.run(owner, defined['pluginId'], defined['packageId'], 'run'))['ok']
    next_version = runner.define(dict(sessionId=owner.id, plugin=dict(kind='existing', pluginId=defined['pluginId']), name='New', purpose='update',
        code=dict(host="def plugin(ctx):\n    ctx.get('runnerGate').entered.append('new apply')\n    ctx.provide('nextVersion', 'ready')\n")))
    update = asyncio.create_task(runner.run(owner, defined['pluginId'], next_version['packageId'], 'update'))
    ending = None
    try:
        await asyncio.wait_for(cleaning.wait(), 1)
        ending = asyncio.create_task(runner.stop(owner, defined['pluginId']))
        await asyncio.sleep(.01)
        assert not ending.done() and not update.done()
        finish.set()
        assert (await asyncio.wait_for(update, 1))['reason'] == 'cancelled'
        assert await asyncio.wait_for(ending, 1) == dict(ok=True)
        assert entered == [] and ctx.get('nextVersion') is None and ctx.get('previousVersion') is None
        row = runner.inventory()[0]
        assert row['currentPackageId'] == defined['packageId']
        assert row['nextPackageId'] == next_version['packageId']
        assert row['latestRun']['status'] == 'stopped' and 'activeRun' not in row
    finally:
        finish.set()
        await asyncio.gather(*(task for task in (update, ending) if task is not None), return_exceptions=True)
        await ctx.fiber.dispose()
