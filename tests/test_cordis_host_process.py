"""Observable lifecycle contracts for process-owned dynamic Python Hosts."""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from dsh.cordis.context import Context
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.extensions.host_runner import DynamicCordisRunner


@pytest_asyncio.fixture
async def host_context():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    try:
        yield ctx, ctx.get('dynamicCordisRunner'), SimpleNamespace(id='owner', steer=lambda _: None)
    finally:
        await ctx.fiber.dispose()


def define(runner, owner, source):
    return runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='owner'),
        name='Process lifecycle', purpose='Real Context ownership', code=dict(host=source)))


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True], ids=['generator', 'async-generator'])
async def test_iterable_effects_keep_state_identity_and_cleanup(host_context, asynchronous):
    ctx, runner, owner = host_context
    source = """state = {'setup': 0, 'cleanup': 0}
def plugin(ctx):
    ctx.provide('processState', state)
    PREFIXdef setup():
        state['setup'] += 1
        yield lambda: state.update(cleanup=state['cleanup'] + 1)
    ctx.effect(setup)
    harness.handle('read', lambda args: state)
""".replace('PREFIX', 'async ' if asynchronous else '')
    defined = define(runner, owner, source)
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    state = ctx.get('processState')
    for _ in range(100):
        if state['setup']:
            break
        await asyncio.sleep(.005)
    assert state == dict(setup=1, cleanup=0)
    state['from_parent'] = 42
    assert (await runner.invoke(defined['pluginId'], started['pluginRunId'], 'read', {}))['value']['from_parent'] == 42
    process = runner.plugins[defined['pluginId']]['run']['hostProcess'].process
    assert (await runner.stop(owner, defined['pluginId']))['ok']
    assert state['cleanup'] == 1
    assert ctx.get('processState') is None
    assert process.poll() is not None


@pytest.mark.asyncio
async def test_deadline_does_not_cover_async_apply_or_later_rpc(host_context):
    ctx, runner, owner = host_context
    runner.timeout = 30
    source = """import asyncio
async def plugin(ctx):
    await asyncio.sleep(.08)
    async def read(args):
        await asyncio.sleep(.08)
        return args
    harness.handle('read', read)
"""
    defined = define(runner, owner, source)
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    assert await runner.invoke(defined['pluginId'], started['pluginRunId'], 'read', {'ok': True}) == dict(ok=True, value={'ok': True})


@pytest.mark.asyncio
async def test_unexpected_process_exit_retracts_registrations_and_reports(host_context):
    ctx, runner, owner = host_context
    messages = []
    owner.steer = messages.append
    ctx.provide('agents', {'owner': owner})
    defined = define(runner, owner, "def plugin(ctx):\n    ctx.provide('processState', {'alive': True})\n")
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok']
    runner.plugins[defined['pluginId']]['run']['hostProcess'].process.kill()
    for _ in range(200):
        if messages:
            break
        await asyncio.sleep(.005)
    assert 'activeRun' not in runner.inventory()[0]
    assert ctx.get('processState') is None
    assert runner.inventory()[0]['latestRun']['status'] == 'failed'
    assert any('Host process' in row['content'][0]['text'] for row in messages)


@pytest.mark.asyncio
async def test_timed_out_run_does_not_kill_another_active_plugin(host_context):
    ctx, runner, owner = host_context
    healthy = define(runner, owner, "state = {'calls': 0}\ndef plugin(ctx):\n    def read(args):\n        state['calls'] += 1\n        return dict(state)\n    harness.handle('read', read)\n")
    started = await runner.run(owner, healthy['pluginId'], healthy['packageId'], 'run')
    assert started['ok']
    process = runner.plugins[healthy['pluginId']]['run']['hostProcess'].process
    runner.timeout = 30
    failed = define(runner, owner, 'sum(range(10 ** 12))\ndef plugin(ctx):\n    pass\n')
    failure = await runner.run(owner, failed['pluginId'], failed['packageId'], 'run')
    assert not failure['ok'] and 'vmTimeoutMs' in failure['message']
    assert process.poll() is None
    assert await runner.invoke(healthy['pluginId'], started['pluginRunId'], 'read', {}) == dict(ok=True, value={'calls': 1})


@pytest.mark.asyncio
async def test_spare_start_failure_returns_diagnostic_and_close_still_cleans_active_run(host_context, monkeypatch):
    from dsh.extensions import host_runner
    ctx, runner, owner = host_context
    factory = host_runner.HostProcess
    def unavailable():
        raise OSError('worker process creation failed')
    monkeypatch.setattr(host_runner, 'HostProcess', unavailable)
    first = define(runner, owner, "def plugin(ctx):\n    ctx.provide('processState', {'alive': True})\n")
    started = await runner.run(owner, first['pluginId'], first['packageId'], 'run')
    assert started['ok']
    process = runner.plugins[first['pluginId']]['run']['hostProcess'].process
    second = define(runner, owner, 'def plugin(ctx):\n    pass\n')
    failure = await runner.run(owner, second['pluginId'], second['packageId'], 'run')
    assert not failure['ok'] and failure['message'] == 'worker process creation failed'
    assert process.poll() is None
    monkeypatch.setattr(host_runner, 'HostProcess', factory)
    assert (await runner.run(owner, second['pluginId'], second['packageId'], 'run'))['ok']
    await runner.close()
    assert process.poll() is not None and ctx.get('processState') is None
