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
    ctx.provide('delay', lambda: asyncio.sleep(.08))
    source = """
async def plugin(ctx):
    await ctx.get('delay')()
    async def read(args):
        await ctx.get('delay')()
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
    for _ in range(1000):
        if messages and 'activeRun' not in runner.inventory()[0]:
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


@pytest.mark.asyncio
async def test_cancelled_child_task_cancels_parent_service_wait(host_context):
    ctx, runner, owner = host_context
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def wait():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    ctx.provide('waitService', wait)
    defined = define(runner, owner, '''import asyncio
def plugin(ctx):
    tasks = []
    async def wait():
        await ctx.get('waitService')()
    def start(args):
        tasks.append(asyncio.create_task(wait()))
    async def cancel(args):
        tasks[0].cancel()
        try:
            await tasks[0]
        except asyncio.CancelledError:
            return {'cancelled': True}
    harness.handle('start', start)
    harness.handle('cancel', cancel)
''')
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    assert (await runner.invoke(defined['pluginId'], started['pluginRunId'], 'start', None))['ok']
    await asyncio.wait_for(entered.wait(), 5)
    reply = await runner.invoke(defined['pluginId'], started['pluginRunId'], 'cancel', None)
    assert reply == dict(ok=True, value=dict(cancelled=True))
    await asyncio.wait_for(cancelled.wait(), 5)


@pytest.mark.asyncio
async def test_frozen_json_retains_readonly_shape_and_roundtrip_identity(host_context):
    from dsh.core.session.json import deep_freeze
    ctx, runner, owner = host_context
    snapshot = deep_freeze({'rows': [{'text': '中文'}]})
    ctx.provide('snapshot', lambda: snapshot)
    defined = define(runner, owner, '''import json
def plugin(ctx):
    snapshot = ctx.get('snapshot')()
    ctx.provide('snapshotEcho', snapshot)
    def read(args):
        rejected = 0
        try:
            snapshot['new'] = True
        except TypeError:
            rejected += 1
        try:
            snapshot['rows'].append(None)
        except TypeError:
            rejected += 1
        return {'snapshot': snapshot, 'json': json.loads(json.dumps(snapshot)), 'rejected': rejected}
    harness.handle('read', read)
''')
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    assert ctx.get('snapshotEcho') is snapshot
    reply = await runner.invoke(defined['pluginId'], started['pluginRunId'], 'read', None)
    assert reply == dict(ok=True, value=dict(snapshot=snapshot, json=snapshot, rejected=2))


@pytest.mark.asyncio
async def test_service_sync_and_async_iterators_cross_process(host_context):
    ctx, runner, owner = host_context
    async def stream():
        for value in ['中文', 'Win7']:
            await asyncio.sleep(0)
            yield value
    ctx.provide('numbers', lambda: range(3))
    ctx.provide('stream', stream)
    defined = define(runner, owner, '''def plugin(ctx):
    async def read(args):
        return {'numbers': list(ctx.get('numbers')()), 'stream': [value async for value in ctx.get('stream')()]}
    harness.handle('read', read)
''')
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    assert await runner.invoke(defined['pluginId'], started['pluginRunId'], 'read', None) == dict(
        ok=True, value=dict(numbers=[0, 1, 2], stream=['中文', 'Win7']))


@pytest.mark.asyncio
async def test_rpc_snapshots_do_not_accumulate_in_run_object_registry(host_context):
    ctx, runner, owner = host_context
    defined = define(runner, owner, '''def plugin(ctx):
    calls = [0]
    def echo(args):
        calls[0] += 1
        return {'call': calls[0], 'payload': args['payload']}
    harness.handle('echo', echo)
''')
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    peer = runner.plugins[defined['pluginId']]['run']['hostProcess'].peer
    before = len(peer.objects), len(peer.containers)
    for index in range(128):
        payload = str(index) + '中文' * 8192
        result = await runner.invoke(defined['pluginId'], started['pluginRunId'], 'echo', dict(payload=payload))
        assert result == dict(ok=True, value=dict(call=index + 1, payload=payload))
    assert (len(peer.objects), len(peer.containers)) == before


@pytest.mark.asyncio
async def test_rpc_snapshots_keep_core_deep_json_contract(host_context):
    ctx, runner, owner = host_context
    defined = define(runner, owner, "def plugin(ctx):\n    harness.handle('echo', lambda args: args)\n")
    started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
    assert started['ok'], started
    value = '中文 bottom'
    for _ in range(2000):
        value = [value]
    reply = await runner.invoke(defined['pluginId'], started['pluginRunId'], 'echo', {'nested': value})
    assert reply['ok'], reply.get('message')
    restored = reply['value']['nested']
    for _ in range(2000):
        assert type(restored) is list and len(restored) == 1
        restored = restored[0]
    assert restored == '中文 bottom'
