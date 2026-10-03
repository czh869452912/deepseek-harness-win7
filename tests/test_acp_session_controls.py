import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
import yaml

from dsh.acp.server import AcpPlugin
from dsh.acp.session_controls import decode_cursor, encode_cursor
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import Session, SessionHeader
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter


class MemoryPersistence:
    def __init__(self):
        self.headers = {}
        self.materialization_error = None
        self.list_gate = None

    async def list(self):
        if self.list_gate is not None:
            await self.list_gate.wait()
        return list(self.headers.values())

    async def ensure_materialized(self, session):
        if self.materialization_error is not None:
            raise self.materialization_error
        self.headers[session.id] = session.header


class OwnedFactory:
    def __init__(self, persistence):
        self.persistence = persistence
        self.live = {}
        self.created = []
        self.resumed = []
        self.disposed = []
        self.cancelled = []
        self.flushed = []
        self.signals = []
        self.failures = {}
        self.create_gate = None
        self.idle_gate = None
        self.entered = asyncio.Event()

    def get(self, session_id):
        return self.live.get(session_id)

    async def flush(self, session):
        self.flushed.append(session.id)
        if 'flush' in self.failures:
            raise self.failures['flush']
        return True

    async def create(self, session_id, meta, options, signal, setup=None):
        self.created.append(session_id)
        self.signals.append(signal)
        self.entered.set()
        if self.create_gate is not None:
            await self.create_gate.wait()
        return self.handle(Session(session_id, header=SessionHeader(session_id, cwd=meta['cwd'])), setup)

    async def resume(self, resume_session_id, options, signal, setup=None):
        self.resumed.append(resume_session_id)
        self.signals.append(signal)
        self.entered.set()
        if self.create_gate is not None:
            await self.create_gate.wait()
        return self.handle(Session(resume_session_id, header=self.persistence.headers[resume_session_id]), setup)

    def handle(self, session, setup=None):
        self.live[session.id] = session

        async def idle():
            if self.idle_gate is not None:
                await self.idle_gate.wait()
            if 'idle' in self.failures:
                raise self.failures['idle']

        async def dispose():
            self.disposed.append(session.id)
            await dispose_context(agent_ctx)
            if self.live.get(session.id) is session:
                del self.live[session.id]
            if 'dispose' in self.failures:
                raise self.failures['dispose']

        agent = SimpleNamespace(id=session.id, session=session, when_idle=idle,
                                cancel=lambda cause: self.cancelled.append(session.id))
        agent_ctx = Context().extend({'agent': agent})
        if setup is not None:
            setup(agent_ctx)
        return SimpleNamespace(agent=agent, dispose=dispose)


def bridge_fixture(page_size=100):
    persistence = MemoryPersistence()
    factory = OwnedFactory(persistence)
    ctx = Context()
    ctx.provide('agents', factory)
    ctx.provide('sessions', factory)
    ctx.provide('sessionPersistence', persistence)
    bridge = AcpPlugin({'sessionListPageSize': page_size})
    return ctx, bridge, persistence, factory


async def dispose_context(ctx):
    await ctx.fiber.dispose()
    await ctx.fiber.await_settled()


@pytest.mark.parametrize('value', [0, -1, True, None, '1', 1.5, float('inf'), float('nan'), 2 ** 53, 10 ** 400])
def test_page_size_rejects_non_positive_or_unsafe_integers(value):
    with pytest.raises(ValueError, match='positive safe integer'):
        AcpPlugin({'sessionListPageSize': value})


@pytest.mark.parametrize('value', ['', '*', 'A', 'bnVsbA', 'W10', 'Wy0xLCJpZCJd', 'WzEsIiJd',
                                   'W3RydWUsImlkIl0', 'WzEsImlkIl0=', 'WyAxLCAiaWQiIF0'])
def test_cursor_encoding_is_strict_and_canonical(value):
    with pytest.raises(ValueError, match='cursor is invalid'):
        decode_cursor(value)


@pytest.mark.parametrize('session_id', ['alpha', '会话', '😀', '\ud800'])
def test_cursor_preserves_exact_unicode_and_safe_integer(session_id):
    encoded = encode_cursor(9007199254740991, session_id)
    assert decode_cursor(encoded) == (9007199254740991, session_id)


@pytest.mark.parametrize('decoded', [None, [], [1.5, 'id'], [2 ** 53, 'id'], [True, 'id'], [1, '']])
def test_decoded_cursor_fields_reject_invalid_values(decoded):
    value = base64.urlsafe_b64encode(json.dumps(decoded).encode('utf-8')).decode('ascii').rstrip('=')
    with pytest.raises(ValueError, match='cursor is invalid'):
        decode_cursor(value)


@pytest.mark.asyncio
async def test_empty_new_session_is_materialized_and_no_agent_fallback_exists(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    try:
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        session_id = created['sessionId']
        assert session_id in persistence.headers and factory.get(session_id) is bridge.sessions[session_id].agent.session
        assert await bridge.list_sessions(ctx, {}) == {'sessions': []}
        assert await bridge.close_session(ctx, created) == {}
        assert await bridge.list_sessions(ctx, {}) == {'sessions': [{'sessionId': session_id, 'cwd': str(tmp_path)}]}
        assert await bridge.resume_session(ctx, dict(created, cwd=str(tmp_path))) == {'configOptions': []}
        assert factory.resumed == [session_id] and factory.disposed == [session_id]
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_list_filters_all_non_resumable_owners_and_uses_stable_keyset(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture(2)
    headers = [
        SessionHeader('subagent', created_at=100, cwd=str(tmp_path), origin='subagent'),
        SessionHeader('child', created_at=100, cwd=str(tmp_path), parent_session='parent'),
        SessionHeader('missing', created_at=100),
        SessionHeader('relative', created_at=100, cwd='relative'),
        SessionHeader('foreign', created_at=100, cwd=str(tmp_path)),
        SessionHeader('activating', created_at=100, cwd=str(tmp_path)),
        SessionHeader('other', created_at=100, cwd=str(tmp_path / 'elsewhere')),
    ] + [SessionHeader(name, created_at=10 if name != 'old' else 9, cwd=str(tmp_path))
         for name in ['😀', 'old', 'β', 'Z', 'a']]
    persistence.headers = {header.id: header for header in headers}
    factory.live['foreign'] = object()
    bridge.activating.add('activating')
    try:
        first = await bridge.list_sessions(ctx, {'cwd': str(tmp_path / 'child' / '..')})
        assert first == {'sessions': [{'sessionId': name, 'cwd': str(tmp_path)} for name in ['Z', 'a']],
                         'nextCursor': encode_cursor(10, 'a')}
        second = await bridge.list_sessions(ctx, {'cwd': str(tmp_path), 'cursor': first['nextCursor']})
        assert [row['sessionId'] for row in second['sessions']] == ['β', '😀']
        third = await bridge.list_sessions(ctx, {'cwd': str(tmp_path), 'cursor': second['nextCursor']})
        assert third == {'sessions': [{'sessionId': 'old', 'cwd': str(tmp_path)}]}
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['unknown', 'subagent', 'parent', 'cwd', 'live', 'activating'])
async def test_resume_rejects_before_factory_and_releases_reservation(tmp_path, reason):
    ctx, bridge, persistence, factory = bridge_fixture()
    header = SessionHeader('saved', cwd=str(tmp_path))
    if reason != 'unknown':
        persistence.headers['saved'] = header
    if reason == 'subagent':
        header.origin = 'subagent'
    if reason == 'parent':
        header.parent_session = 'parent'
    if reason == 'cwd':
        header.cwd = str(tmp_path / 'other')
    if reason == 'live':
        factory.live['saved'] = object()
    if reason == 'activating':
        bridge.activating.add('saved')
    try:
        with pytest.raises(ValueError):
            await bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': str(tmp_path)})
        assert not factory.resumed
        if reason != 'activating':
            assert not bridge.activating
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_resume_reserves_across_awaits_and_retry_after_failure(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    persistence.headers['saved'] = SessionHeader('saved', cwd=str(tmp_path))
    factory.create_gate = asyncio.Event()
    pending = asyncio.create_task(bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': str(tmp_path)}))
    try:
        await asyncio.wait_for(factory.entered.wait(), 2)
        assert await bridge.list_sessions(ctx, {}) == {'sessions': []}
        with pytest.raises(ValueError, match='already active'):
            await bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': str(tmp_path)})
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        assert not bridge.activating
        factory.create_gate.set()
        assert await bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': str(tmp_path)}) == {'configOptions': []}
        assert factory.resumed == ['saved', 'saved']
    finally:
        factory.create_gate.set()
        await asyncio.gather(pending, return_exceptions=True)
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['new', 'resume', 'list'])
async def test_pre_abort_never_reaches_factory_or_storage(tmp_path, operation):
    ctx, bridge, persistence, factory = bridge_fixture()
    controller = AbortController()
    controller.abort(RuntimeError('request cancelled'))
    try:
        method = getattr(bridge, operation + '_session' if operation != 'list' else 'list_sessions')
        with pytest.raises(RuntimeError, match='request cancelled'):
            await method(ctx, {'cwd': str(tmp_path), 'sessionId': 'saved'}, controller.signal)
        assert not factory.created and not factory.resumed and not bridge.activating
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_closed_late_factory_result_is_disposed_not_published(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    factory.create_gate = asyncio.Event()
    pending = asyncio.create_task(bridge.new_session(ctx, {'cwd': str(tmp_path)}))
    try:
        await asyncio.wait_for(factory.entered.wait(), 2)
        await bridge.close(ctx)
        assert factory.signals[0].aborted
        factory.create_gate.set()
        with pytest.raises(RuntimeError, match='disposed'):
            await pending
        assert factory.disposed == factory.created and not factory.live
        assert not bridge.sessions and not persistence.headers
    finally:
        factory.create_gate.set()
        await asyncio.gather(pending, return_exceptions=True)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_materialization_failure_disposes_without_publishing(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    persistence.materialization_error = RuntimeError('materialization failed')
    try:
        with pytest.raises(RuntimeError, match='materialization failed'):
            await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        assert factory.created == factory.disposed and not factory.live and not bridge.sessions
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_concurrent_close_shares_drain_and_rejects_new_work(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
    factory.idle_gate = asyncio.Event()
    first = asyncio.create_task(bridge.close_session(ctx, created))
    second = asyncio.create_task(bridge.close_session(ctx, created))
    try:
        await asyncio.sleep(0)
        with pytest.raises(ValueError, match='session is closing'):
            await bridge.prompt(ctx, dict(created, prompt=[{'type': 'text', 'text': 'too late'}]))
        assert not first.done() and not second.done()
        factory.idle_gate.set()
        assert await asyncio.gather(first, second) == [{}, {}]
        assert factory.disposed == factory.created and factory.cancelled == factory.created
    finally:
        factory.idle_gate.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_cancelled_close_observer_cannot_release_record_before_drain(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
    factory.idle_gate = asyncio.Event()
    pending = asyncio.create_task(bridge.close_session(ctx, created))
    try:
        await asyncio.sleep(0)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        assert created['sessionId'] in bridge.sessions
        assert await bridge.list_sessions(ctx, {}) == {'sessions': []}
        factory.idle_gate.set()
        await bridge.close_session(ctx, created)
        assert created['sessionId'] not in bridge.sessions and factory.disposed == factory.created
    finally:
        factory.idle_gate.set()
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['idle', 'flush', 'dispose', 'descendants'])
async def test_close_failure_still_disposes_exact_owner_and_releases_record(tmp_path, stage):
    ctx, bridge, persistence, factory = bridge_fixture()
    created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
    failure = RuntimeError(stage + ' failed')
    if stage == 'descendants':
        async def drain(parents):
            assert parents == [bridge.sessions[created['sessionId']].agent]
            raise failure
        ctx.provide('subagents', SimpleNamespace(drainContinuableDescendants=drain))
    else:
        factory.failures[stage] = failure
    try:
        with pytest.raises(RuntimeError, match='session close failed.*' + stage):
            await bridge.close_session(ctx, created)
        assert not bridge.sessions and not factory.live and factory.created == factory.disposed
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_bridge_close_cancels_all_owners_before_any_drain_and_aggregates(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    await bridge.new_session(ctx, {'cwd': str(tmp_path)})
    await bridge.new_session(ctx, {'cwd': str(tmp_path)})
    factory.idle_gate = asyncio.Event()
    factory.failures = {'idle': RuntimeError('idle failed'), 'flush': RuntimeError('flush failed')}
    pending = asyncio.create_task(bridge.close(ctx))
    try:
        await asyncio.sleep(0)
        assert factory.cancelled == factory.created and not factory.disposed
        factory.idle_gate.set()
        with pytest.raises(RuntimeError, match='2 session.*idle failed.*flush failed'):
            await pending
        assert factory.disposed == factory.created and not factory.live and not bridge.sessions
    finally:
        factory.idle_gate.set()
        await asyncio.gather(pending, return_exceptions=True)
        await dispose_context(ctx)


async def boot_profile(tmp_path, backend, monkeypatch):
    home = tmp_path / 'home'
    profile = home / 'profiles' / 'acp-controls'
    init_profile(str(profile), [], 'startup')
    rows = [{'id': name, 'name': '@deepseek-ai/dsh-' + name} for name in
            ('session', 'tools', 'system-prompt', 'llm', 'agent', 'agent-loop', 'acp')]
    config = {'root': str(tmp_path / 'sessions'), 'packChunks': False} if backend == 'jsonl' else {
        'path': str(tmp_path / 'sessions.db')}
    rows.append({'id': 'persistence', 'name': '@deepseek-ai/dsh-session-persistence-' + backend, 'config': config})
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    runtime = await run_profile({'profile': 'acp-controls', 'dshHome': str(home), 'args': [], 'waitForExit': False})
    ctx = runtime['ctx']
    adapter = StrictMockLlmAdapter([{'text': 'persisted answer'}, {'text': 'continued answer'}])
    ctx.get('llm').register_adapter(['openai'], adapter)
    monkeypatch.setattr(ctx.get('llm'), 'chat_completion_stream', adapter.chat_completion_stream)
    bridge = next(entry.fiber.plugin for entry in ctx.get('loader').entries
                  if entry.options.get('name') == '@deepseek-ai/dsh-acp')
    return runtime, bridge, adapter


async def stop_profile(runtime):
    runtime['shutdown'].shutdown(0)
    await runtime['shutdown'].wait()


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['jsonl', 'sqlite'])
async def test_actual_profile_empty_materialization_history_and_new_context_resume(tmp_path, backend, monkeypatch):
    runtime, bridge, adapter = await boot_profile(tmp_path, backend, monkeypatch)
    ctx = runtime['ctx']
    try:
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        await bridge.close_session(ctx, created)
        assert await bridge.list_sessions(ctx, {}) == {'sessions': [
            {'sessionId': created['sessionId'], 'cwd': str(tmp_path)}]}
        await bridge.resume_session(ctx, dict(created, cwd=str(tmp_path)))
        assert await bridge.prompt(ctx, dict(created, prompt=[{'type': 'text', 'text': 'remember this'}])) == {
            'stopReason': 'end_turn'}
        saved_events = list(bridge.sessions[created['sessionId']].agent.session.events)
        await bridge.close_session(ctx, created)
        assert ctx.get('agents').get(created['sessionId']) is None
    finally:
        await stop_profile(runtime)
    runtime, bridge, adapter = await boot_profile(tmp_path, backend, monkeypatch)
    ctx = runtime['ctx']
    try:
        await bridge.resume_session(ctx, dict(created, cwd=str(tmp_path)))
        agent = bridge.sessions[created['sessionId']].agent
        assert agent.session.events[:-1] == saved_events
        marker = agent.session.events[-1]
        assert set(marker) == {'type', 'seq', 'time', 'data'}
        assert marker['type'] == 'session/end-seed' and marker['data'] == {}
        assert marker['seq'] == saved_events[-1]['seq'] + 1 and isinstance(marker['time'], int)
        assert await bridge.prompt(ctx, dict(created, prompt=[{'type': 'text', 'text': 'continue'}])) == {
            'stopReason': 'end_turn'}
        assert 'remember this' in str(adapter.requests)
    finally:
        await stop_profile(runtime)
