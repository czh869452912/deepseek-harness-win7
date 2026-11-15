import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.api.session_history_authorized import SessionHistoryController
from dsh.api.session_state_authorized import SessionStateController, StateListener
from dsh.core.abort import AbortController
from dsh.cordis import Context
from dsh.typert.remote import RemoteError
from scripts.rc022_session_state_probe import observe


EMPTY = dict(cursor=-1, active=False, running=False, queue=None, pendingInput=[])


@pytest.mark.asyncio
async def test_actual_agent_waits_are_passive_and_cold_output_is_readable(tmp_path):
    rows = await observe(tmp_path)
    named = {row['name']: row for row in rows}
    assert len(rows) == 20
    assert named['queue']['value'][1]['rpcId'] == 'rpc'
    assert [item['placement'] for item in named['queue']['value']] == ['queued', 'steering', 'context']
    assert named['pending']['value'] == ['approval', 'question', 'other']
    assert named['running-timeout']['value']['reason'] == 'timeout'
    assert named['running-timeout']['stillRunning'] and not named['running-timeout']['callerAborted']
    assert named['caller-cancel']['same'] and named['caller-cancel']['stillRunning']
    assert named['pending-periodic']['value']['pendingInput'] == ['question']
    assert named['cold-state']['agentAbsent'] and named['cold-state']['value']['queue'] is None
    assert named['cold-wait']['value']['outputRecords'] == 1
    assert named['after-execution']['value']['reason'] == 'idle'


@pytest.mark.asyncio
async def test_async_stale_reads_are_discarded_and_invalidations_coalesced():
    ctx = Context(); abort = AbortController(); first = asyncio.Future(); reading = asyncio.Event(); calls = []
    async def read(signal):
        calls.append(signal)
        if len(calls) == 1:
            reading.set()
            return await first
        return dict(EMPTY, cursor=2)
    listener = StateListener(ctx, 'target', abort.signal, read); states = listener.observeStates()
    task = asyncio.ensure_future(states.__anext__())
    try:
        await reading.wait()
        ctx.emit('session/event', NS(id='other'), {})
        ctx.emit('session/event', NS(id='target'), {})
        ctx.emit('session/event', NS(id='target'), {})
        first.set_result(EMPTY)
        assert await task == dict(state=dict(EMPTY, cursor=2), revision=2)
        assert len(calls) == 2 and not listener.isCurrent(0)
        pending = asyncio.ensure_future(states.__anext__()); await asyncio.sleep(0)
        await ctx.fiber.dispose()
        with pytest.raises(StopAsyncIteration): await pending
        assert calls[0].aborted
    finally:
        listener.dispose(); await states.aclose(); await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_periodic_refresh_and_all_agent_lifecycle_events():
    ctx = Context(); abort = AbortController()
    async def read(_): return EMPTY
    listener = StateListener(ctx, 'target', abort.signal, read); states = listener.observeStates(5)
    try:
        assert (await states.__anext__())['revision'] == 0
        assert (await states.__anext__())['revision'] == 1
        for revision, event in enumerate(('agent/created', 'agent/status', 'agent/disposed'), 2):
            ctx.emit(event, dict(agent=NS(id='target')))
            assert (await states.__anext__())['revision'] == revision
    finally:
        listener.dispose(); await states.aclose(); await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_registration_failure_detaches_abort_and_prior_hooks():
    ctx = Context(); abort = AbortController(); original = ctx.on; disposals = []
    def on(*args, **kwargs):
        if disposals: raise RuntimeError('registration failed')
        disposals.append(False)
        return lambda: disposals.__setitem__(0, True)
    ctx.on = on
    try:
        with pytest.raises(RuntimeError, match='registration failed'):
            StateListener(ctx, 'target', abort.signal, lambda _: None)
        assert disposals == [True] and not abort.signal._dom_listeners
    finally:
        ctx.on = original; await ctx.fiber.dispose()


def controller_fixture():
    ctx = Context(); abort = AbortController(); calls = []
    async def output(*args): calls.append(args); return dict(records=[], truncated=False)
    controller = SessionStateController(ctx, NS(assistantOutput=output))
    return ctx, abort, controller, calls


@pytest.mark.asyncio
async def test_wait_reports_timeout_before_first_state_and_preserves_unrelated_failure():
    for unrelated in (False, True):
        ctx, abort, controller, calls = controller_fixture()
        primary = RemoteError('gateway/internal', 'disk read failed', {})
        async def read(_, signal):
            await signal.wait_aborted()
            if unrelated: raise primary
            raise RemoteError('gateway/cancelled', 'cancelled', {}, cause=signal.reason)
        controller.readState = read
        try:
            with pytest.raises(RemoteError) as caught:
                await controller.wait(dict(sessionId='target', timeoutMs=5), abort.signal)
            assert (caught.value is primary) if unrelated else caught.value.code == 'session/wait-timeout'
            assert not calls and not abort.signal.aborted
        finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_last_accepted_state_survives_stale_sample_and_timeout(monkeypatch):
    ctx, abort, controller, calls = controller_fixture()
    async def states(self, refresh=None):
        yield dict(state=dict(EMPTY, running=True), revision=0)
        yield dict(state=dict(EMPTY, running=True, cursor=7), revision=9)
        await self.signal.wait_aborted()
        self.signal.throwIfAborted()
    monkeypatch.setattr(StateListener, 'observeStates', states)
    try:
        value = await controller.wait(dict(sessionId='target', timeoutMs=100), abort.signal)
        assert value['reason'] == 'timeout' and value['state']['cursor'] == -1
        assert calls[0] == ('target', -1, -1, 50, abort.signal)
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_armed_next_read_failure_is_observed_after_stopping_state(monkeypatch):
    ctx, abort, controller, calls = controller_fixture()
    async def states(self, refresh=None):
        yield dict(state=EMPTY, revision=0)
        raise RuntimeError('next read failed')
    monkeypatch.setattr(StateListener, 'observeStates', states)
    try:
        value = await controller.wait(dict(sessionId='target', afterSeq=3, maxMessages=2), abort.signal)
        assert value['reason'] == 'idle'
        assert calls[0] == ('target', 3, -1, 2, abort.signal)
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_early_end_is_not_reported_as_idle(monkeypatch):
    ctx, abort, controller, calls = controller_fixture()
    async def states(self, refresh=None):
        if False: yield
    monkeypatch.setattr(StateListener, 'observeStates', states)
    try:
        with pytest.raises(RemoteError) as caught:
            await controller.wait(dict(sessionId='target'), abort.signal)
        assert caught.value.code == 'session/observation-ended' and not calls
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_live_redirect_rereads_once_and_missing_cwd_is_not_found():
    ctx, abort, controller, _ = controller_fixture(); session = NS(id='target', seq=4, header=NS(cwd='C:/state'))
    agent = NS(session=session, status='running', inbox=NS(nextTurn=[], nextStep=[])); lookups = [None, agent]
    ctx.set_service('agents', NS(get=lambda _: lookups.pop(0) if lookups else agent))
    ctx.set_service('typertGateway', NS(getPendingRemoteEvents=lambda: []))
    async def observation(request, signal, callback):
        assert request['projection'] is False
        return callback(NS(source='live'))
    controller.history_controller = NS(usingObservation=observation)
    try:
        assert await controller.state(dict(sessionId='target'), abort.signal) == dict(cursor=3, active=True, running=True, queue=[], pendingInput=[])
        session.header.cwd = None
        with pytest.raises(RemoteError) as caught: await controller.state(dict(sessionId='target'), abort.signal)
        assert caught.value.code == 'session/not-found'
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_new_remote_faces_use_gateway_session_admission(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from dsh.typert.remote import TypertRemoteService
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.api.session_resource import register_session_resource
    from dsh.host.connection.peer import Peer
    fixture = await setup(tmp_path / 'journal'); ctx = fixture.ctx; abort = AbortController(); stream = None
    try:
        for plugin in (CurrentTypertRegistry, RemoteAccessService, AuthorizedGatewayService): await ctx.plugin(plugin)
        register_session_resource(ctx)
        api = AuthorizedSessionController.__new__(AuthorizedSessionController)
        TypertRemoteService.__init__(api, ctx, 'sessionController', dict(namespace='session'))
        api.state_controller = SessionStateController(ctx, SessionHistoryController(ctx))
        ctx.remoteAccess.registerPolicy('guest', dict(bindings=lambda *_: [dict(resource=dict(kind='session', id='shared'), role=dict(actions=['session/state', 'session/wait', 'session/observeState']))]))
        peer = Peer(ctx, dict(principal=dict(kind='guest', id='guest')))
        await ctx.agents.create(dict(sessionId='shared', meta=dict(cwd='C:/state'), agentOptions=dict(provider='script', model='model')))
        def call(method, identity):
            return dict(namespace='session', method=method, args=dict(request=dict(sessionId=identity)), peer=peer, signal=abort.signal)
        for method in ('state', 'wait'):
            with pytest.raises(RemoteError) as caught: await ctx.typertGateway.invoke(call(method, 'hidden'))
            assert caught.value.code == 'remote-access/denied'
        assert (await ctx.typertGateway.invoke(call('state', 'shared')))['active']
        assert (await ctx.typertGateway.invoke(call('wait', 'shared')))['reason'] == 'idle'
        stream = await ctx.typertGateway.stream(call('observeState', 'shared'))
        assert (await stream.__anext__())['queue'] == []
        abort.abort()
        with pytest.raises(RemoteError) as caught: await stream.__anext__()
        assert caught.value.code == 'gateway/cancelled'
    finally:
        abort.abort()
        if stream is not None: await stream.aclose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['revision', 'agent', 'session', 'driver-failure'])
async def test_idle_race_rechecks_ownership_and_preserves_driver_failure(monkeypatch, change):
    ctx, abort, controller, calls = controller_fixture(); entered = asyncio.Event(); release = asyncio.Event(); next_read = asyncio.Event()
    session = NS(); agent = NS(session=session)
    owner = [agent]; current_session = [session]; revision = [True]
    async def idle():
        entered.set(); await release.wait()
        if change == 'driver-failure': raise RuntimeError('driver failed')
    agent.whenIdle = idle
    ctx.set_service('agents', NS(get=lambda _: owner[0])); ctx.set_service('sessions', NS(get=lambda _: current_session[0]))
    async def states(self, refresh=None):
        yield dict(state=dict(EMPTY, active=True, queue=[]), revision=0)
        await next_read.wait()
        yield dict(state=EMPTY, revision=1)
        await self.signal.wait_aborted()
    monkeypatch.setattr(StateListener, 'observeStates', states)
    monkeypatch.setattr(StateListener, 'isCurrent', lambda self, value: revision[0] if value == 0 else True)
    operation = asyncio.ensure_future(controller.wait(dict(sessionId='target'), abort.signal))
    try:
        await entered.wait()
        if change == 'revision': revision[0] = False
        if change == 'agent': owner[0] = None
        if change == 'session': current_session[0] = NS()
        release.set(); await asyncio.sleep(0); next_read.set()
        if change == 'driver-failure':
            with pytest.raises(RuntimeError, match='driver failed'): await operation
            assert not calls
        else:
            value = await operation
            assert value['reason'] == 'idle' and value['state']['active'] is False
    finally:
        abort.abort(); release.set(); next_read.set(); await asyncio.gather(operation, return_exceptions=True); await ctx.fiber.dispose()
