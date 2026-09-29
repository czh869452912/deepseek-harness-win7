import asyncio
from types import SimpleNamespace
import pytest

from dsh.core.abort import AbortController
from dsh.terminal.service import TerminalSessionService, TerminalError, TerminalBackendCleanupError
from dsh.cordis.events import AggregateError
from test_subagent_in_process import setup


class BackendSession:
    motd, pid = 'ready', 123

    def __init__(self):
        self.closed = False
        self.failure = False
        self.fence = None

    def status(self):
        return dict(kind='exited' if self.closed else 'running')

    def startSend(self, request):
        return SimpleNamespace(done=asyncio.get_running_loop().create_future())

    def read(self, request):
        return dict(text='output', totalLines=1, lineBegin=0, lineEnd=1, truncated=False)

    async def close(self, reason):
        if self.fence is not None:
            await self.fence.wait()
        if self.failure:
            raise RuntimeError('cleanup failed')
        self.closed = True


class Backend:
    type = 'fixture'

    def __init__(self):
        self.sessions = []
        self.entered = asyncio.Event()
        self.release = None

    async def spawn(self, spec):
        self.signal = spec['signal']
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        session = BackendSession()
        self.sessions.append(session)
        return session


@pytest.mark.asyncio
async def test_exact_owner_send_exclusion_duplicate_names_and_awaited_close():
    ctx, _, owner = await setup()
    await ctx.plugin(TerminalSessionService)
    terminals = ctx.get('terminals')
    backend = Backend()
    terminals.registerBackend(backend)
    stranger = await ctx.get('agents').create('stranger')
    try:
        spawned = await terminals.spawn(owner.agent, dict(type='fixture', name='shell'))
        identity = spawned['sessionId']
        assert spawned == dict(sessionId='pty-1', type='fixture', name='shell', pid=123, status=dict(kind='running'), motd='ready')
        with pytest.raises(TerminalError) as error:
            terminals.read(stranger.agent, identity)
        assert error.value.code == 'FOREIGN_SESSION'
        with pytest.raises(TerminalError) as error:
            await terminals.spawn(owner.agent, dict(type='fixture', name='shell'))
        assert error.value.code == 'DUPLICATE_NAME'
        operation = terminals.startSend(owner.agent, identity, dict(text='echo', submit=True))
        with pytest.raises(TerminalError) as error:
            terminals.startSend(owner.agent, identity, dict(text='', submit=True))
        assert error.value.code == 'SEND_ACTIVE'
        operation.done.set_result({})
        await asyncio.sleep(0)
        session = backend.sessions[0]
        session.fence = asyncio.Event()
        first = asyncio.create_task(terminals.kill(owner.agent, identity))
        second = asyncio.create_task(terminals.kill(owner.agent, identity))
        await asyncio.sleep(0)
        assert terminals.hasOwnerActivity(owner.agent)
        session.fence.set()
        assert await asyncio.gather(first, second) == [True, False]
        assert not terminals.hasOwnerActivity(owner.agent)
    finally:
        await stranger.dispose()
        await owner.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unpublished_spawn_owner_disposal_rolls_back_and_name_reservation():
    ctx, _, owner = await setup()
    await ctx.plugin(TerminalSessionService)
    terminals, backend = ctx.get('terminals'), Backend()
    terminals.registerBackend(backend)
    backend.release = asyncio.Event()
    pending = asyncio.create_task(terminals.spawn(owner.agent, dict(type='fixture', name='shell')))
    await backend.entered.wait()
    assert terminals.hasOwnerActivity(owner.agent)
    with pytest.raises(TerminalError) as error:
        await terminals.spawn(owner.agent, dict(type='fixture', name='shell'))
    assert error.value.code == 'DUPLICATE_NAME'
    disposal = asyncio.create_task(owner.dispose())
    await asyncio.wait_for(backend.signal.wait_aborted(), 2)
    assert not disposal.done()
    backend.release.set()
    with pytest.raises(TerminalError) as error:
        await pending
    assert error.value.code == 'OWNER_NOT_LIVE'
    await disposal
    assert backend.sessions[0].closed
    assert not terminals.list(owner.agent) and not terminals.hasOwnerActivity(owner.agent)
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_close_keeps_authority_and_can_retry():
    ctx, _, owner = await setup()
    await ctx.plugin(TerminalSessionService)
    terminals, backend = ctx.get('terminals'), Backend()
    terminals.registerBackend(backend)
    try:
        identity = (await terminals.spawn(owner.agent, dict(type='fixture')))['sessionId']
        backend.sessions[0].failure = True
        with pytest.raises(RuntimeError, match='cleanup failed'):
            await terminals.kill(owner.agent, identity)
        assert terminals.hasOwnerActivity(owner.agent)
        backend.sessions[0].failure = False
        assert await terminals.kill(owner.agent, identity)
    finally:
        await owner.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_unpublished_cleanup_stays_visible_until_teardown_reports_it():
    ctx, _, owner = await setup()
    fiber = await ctx.plugin(TerminalSessionService)
    terminals = ctx.get('terminals')
    class Broken:
        type = 'broken'
        async def spawn(self, spec):
            raise TerminalBackendCleanupError(ValueError('spawn failed'), RuntimeError('rollback failed'))
    terminals.registerBackend(Broken())
    with pytest.raises(TerminalBackendCleanupError):
        await terminals.spawn(owner.agent, dict(type='broken'))
    assert terminals.hasOwnerActivity(owner.agent)
    with pytest.raises(AggregateError):
        await terminals.dispose_all()
    assert not terminals.hasOwnerActivity(owner.agent) and not terminals.backends
    await fiber.dispose()
    await owner.dispose()
    await ctx.fiber.dispose()
