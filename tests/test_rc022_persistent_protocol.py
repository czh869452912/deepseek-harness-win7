import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.core.abort import AbortController
from dsh.terminal.authorized import AuthorizedPersistentPwshPlugin
from dsh.terminal.persistent_authorized import CLIPPED
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_tool_registry_transcripts_retention_and_cleanup(tmp_path):
    from scripts.rc022_persistent_protocol_probe import observe
    rows = {row['name']: row for row in await observe(tmp_path)}
    for row in rows.values():
        assert row['closed'] and row['retained'] == 0
    assert rows['complete']['result'] == dict(value='hello')
    assert rows['padded-status']['result'] == dict(value='kept  \n[exit code: 2]')
    assert rows['torn-status']['result'] == dict(value='hello\n[exit code: 7]')
    assert rows['nonzero-empty']['result'] == dict(value='[exit code: 7]')
    assert rows['empty-read-fallback']['result'] == dict(value='hello')
    assert rows['incremental-fallback']['result'] == dict(value='from increment')
    assert rows['paged-scrollback']['result'] == dict(value='one\ntwo\nthree')
    assert rows['clip-astral']['result'] == dict(value='A😀' + CLIPPED)
    assert rows['cancel']['result'] == dict(value='') and rows['cancel']['retainedBeforeUnload'] == 0
    assert rows['timeout']['retainedBeforeUnload'] == 0
    assert 'partial\n' in rows['timeout']['result']['value']
    for name in ('exit-code', 'exit-signal', 'exit-unknown', 'exit-between-sends'):
        assert rows[name]['retainedBeforeUnload'] == 0
    assert rows['spawn-failure-retry']['retry'] == rows['send-failure-retry']['retry'] == dict(value='recovered')


async def mount(tmp_path, spawn=None):
    fixture = await setup(tmp_path)
    ctx = fixture.ctx
    closed = []
    async def kill(owner, identity, reason):closed.append(identity)
    ctx.set_service('terminals', NS(spawn=spawn, list=lambda owner:[dict(sessionId='shared')], kill=kill))
    fiber = await ctx.plugin(AuthorizedPersistentPwshPlugin)
    handle = await ctx.agents.create(dict(sessionId='owner', agentOptions=dict(provider='script', model='model')))
    return fixture, fiber.plugin, handle.agent, closed


@pytest.mark.asyncio
async def test_concurrent_creation_shares_pending_and_publishes_once(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event();calls=[]
    async def spawn(owner, request, signal):
        calls.append(request);entered.set();await release.wait();return dict(sessionId='shared')
    fixture, plugin, owner, closed = await mount(tmp_path, spawn)
    try:
        first = asyncio.create_task(plugin.get(owner, fixture.signal));await entered.wait()
        second = asyncio.create_task(plugin.get(owner, fixture.signal));await asyncio.sleep(0)
        release.set();assert await asyncio.gather(first, second) == ['shared', 'shared']
        assert len(calls) == 1
        await plugin.reset(owner, 'test reset')
        assert closed == ['shared'] and owner not in plugin.pending and owner not in plugin.live
    finally:
        release.set();await fixture.ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unload_cancels_creation_and_waits_for_rollback(tmp_path):
    entered, rolled_back = asyncio.Event(), asyncio.Event()
    async def spawn(owner, request, signal):
        entered.set();await signal.wait_aborted();rolled_back.set();signal.throwIfAborted()
    fixture, plugin, owner, _ = await mount(tmp_path, spawn)
    try:
        pending = asyncio.create_task(plugin.get(owner, fixture.signal));await entered.wait()
        await plugin.dispose()
        with pytest.raises(RuntimeError, match='disposed during shell creation'):await pending
        assert rolled_back.is_set() and not plugin.creating and not plugin.live and owner not in plugin.pending
    finally:await fixture.ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_queued_call_does_not_start_another_command(tmp_path):
    fixture, plugin, owner, _ = await mount(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event();commands=[]
    async def command(owner, text, signal):
        commands.append(text);entered.set();await release.wait();return 'first result'
    plugin.command = command
    controller = AbortController()
    try:
        first = asyncio.create_task(plugin.execute(dict(command='first'), NS(agent=owner, signal=fixture.signal)))
        await entered.wait()
        second = asyncio.create_task(plugin.execute(dict(command='second'), NS(agent=owner, signal=controller.signal)))
        await asyncio.sleep(0);controller.abort(RuntimeError('queued cancel'));release.set()
        assert await asyncio.gather(first, second) == ['first result', ''] and commands == ['first']
    finally:
        release.set();await fixture.ctx.fiber.dispose()
