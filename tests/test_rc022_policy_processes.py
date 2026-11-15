import asyncio
from types import SimpleNamespace

import pytest

from scripts.rc022_policy_processes_probe import observe


@pytest.mark.asyncio
async def test_policy_owned_cleanup_matches_admission_and_unload_boundaries():
    rows = {row['action']: row for row in await observe()}
    assert all(row['unrelatedIgnored'] and row['sharedCleanup'] for row in rows.values())
    for action in ('policy', 'escalated', 'unpublished', 'no-store', 'dispose'):
        assert rows[action]['started'] == rows[action]['finalCount'] == 1
        assert rows[action]['result'] == 'done'
    assert rows['unscoped']['finalCount'] == rows['detached']['finalCount'] == 0
    for action in ('retry', 'fanout'):
        assert rows[action]['result'] == 'cleanup failed'
        assert rows[action]['retryCount'] == 2
        assert rows[action]['warnings']
    assert rows['fanout']['waitsForPeer']


@pytest.mark.asyncio
async def test_cancelled_admission_does_not_cancel_owned_process_cleanup():
    from dsh.cordis import Context
    from dsh.code_runtime.policy_processes import PolicyProcesses
    ctx = Context()
    processes = PolicyProcesses(ctx)
    gate = asyncio.get_running_loop().create_future()
    calls = []
    async def release():
        calls.append(1)
        await gate
    processes.register(dict(sessionId='session', mode='read-only'), release)
    ctx.emit('session/event', SimpleNamespace(id='session'),
             dict(type='sandbox/mode', data=dict(mode='workspace-write')))
    waiting = asyncio.create_task(processes.wait('session'))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert not gate.cancelled()
    gate.set_result(None)
    await processes.wait('session')
    await ctx.fiber.dispose()
    assert calls == [1] and not processes.processes


@pytest.mark.asyncio
async def test_synchronous_release_failure_remains_retryable():
    from dsh.cordis import Context
    from dsh.code_runtime.policy_processes import PolicyProcesses
    ctx = Context()
    processes = PolicyProcesses(ctx)
    calls = []
    def release():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('synchronous failure')
    processes.register(dict(sessionId='session', mode='read-only'), release)
    ctx.emit('session/event', SimpleNamespace(id='session'),
             dict(type='sandbox/mode', data=dict(mode='workspace-write')))
    with pytest.raises(RuntimeError, match='synchronous failure'):
        await processes.wait('session')
    await processes.wait('session')
    await ctx.fiber.dispose()
    assert len(calls) == 2
