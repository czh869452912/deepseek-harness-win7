import asyncio
from types import SimpleNamespace

import pytest
import yaml

from dsh.acp.server import AcpPlugin, SessionRecord
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
from dsh.cordis.context import Context
from dsh.core.session import Session
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter


def record(session_id, turn):
    owned = SessionRecord(SimpleNamespace(session=Session(session_id)))
    owned.inflight_prompt = {'msg_id': session_id + '-message', 'turn': turn,
                             'stop_reason': 'end_turn', 'end_reason': None}
    return owned


def test_turn_end_is_owned_by_exact_session_and_claimed_turn():
    bridge = AcpPlugin()
    first, second = record('alpha', 1), record('beta', 1)
    bridge.sessions = {'alpha': first, 'beta': second}
    bridge._on_session_event(first.agent.session, {'type': 'turn/end',
        'data': {'turn': 1, 'reason': {'kind': 'interrupted'}}})
    assert first.inflight_prompt['stop_reason'] == 'cancelled'
    assert second.inflight_prompt['stop_reason'] == 'end_turn'


@pytest.mark.parametrize('impostor', [False, True])
def test_wrong_turn_or_same_id_session_impostor_cannot_change_result(impostor):
    bridge = AcpPlugin()
    owned = record('alpha', 2)
    bridge.sessions = {'alpha': owned}
    observed = Session('alpha') if impostor else owned.agent.session
    bridge._on_session_event(observed, {'type': 'turn/end',
        'data': {'turn': 2 if impostor else 1, 'reason': {'kind': 'max-tokens'}}})
    assert owned.inflight_prompt['stop_reason'] == 'end_turn'


@pytest.mark.parametrize('kind', ['completed', 'max-tokens', 'interrupted'])
def test_unclaimed_prompt_never_adopts_an_unrelated_turn(kind):
    bridge = AcpPlugin()
    owned = record('alpha', None)
    bridge.sessions = {'alpha': owned}
    bridge._on_session_event(owned.agent.session, {'type': 'turn/end',
        'data': {'turn': 1, 'reason': {'kind': kind}}})
    assert owned.inflight_prompt['end_reason'] is None


@pytest.mark.parametrize('source', ['owned', 'same-id', 'different-session', 'unrelated-message'])
def test_inbox_claim_requires_exact_agent_and_prompt_message(source):
    bridge = AcpPlugin()
    owned = record('alpha', None)
    bridge.sessions = {'alpha': owned}
    agent = owned.agent if source in ('owned', 'unrelated-message') else record(
        'alpha' if source == 'same-id' else 'beta', None).agent
    bridge._on_inbox_claimed({'agent': agent,
        'message': {'id': 'other' if source == 'unrelated-message' else 'alpha-message'}, 'turn': 4})
    assert owned.inflight_prompt['turn'] == (4 if source == 'owned' else None)


class ControlledAgent:
    def __init__(self, ctx, session_id):
        self.ctx, self.session = ctx, Session(session_id)
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.message = None
        self.cancelled = []
        self.enqueue_error = None
        self.idle_error = None

    def followup(self, message):
        if self.enqueue_error:
            raise self.enqueue_error
        self.message = message
        self.ctx.emit('agent/inbox/claimed', {'agent': self, 'message': message, 'turn': 2})

    async def when_idle(self):
        self.entered.set()
        await self.release.wait()
        if self.idle_error:
            raise self.idle_error

    def cancel(self, cause):
        self.cancelled.append(cause)

    def end(self, kind, turn=2, error=None):
        reason = {'kind': kind}
        if error is not None:
            reason['error'] = error
        self.ctx.emit('session/event', self.session,
            {'type': 'turn/end', 'data': {'turn': turn, 'reason': reason}})


def controlled_bridge():
    ctx, bridge = Context(), AcpPlugin()
    bridge.apply(ctx)
    first, second = ControlledAgent(ctx, 'alpha'), ControlledAgent(ctx, 'beta')
    bridge.sessions = {agent.session.id: SessionRecord(agent) for agent in (first, second)}
    return ctx, bridge, first, second


async def send(bridge, ctx, session_id):
    return await bridge.prompt(ctx, {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': 'go'}]})


async def close_context(ctx):
    await ctx.fiber.dispose()
    await ctx.fiber.await_settled()


@pytest.mark.asyncio
async def test_concurrent_prompt_results_cannot_be_overwritten_by_neighbor_or_stale_turn():
    ctx, bridge, first, second = controlled_bridge()
    pending = [asyncio.create_task(send(bridge, ctx, agent.session.id)) for agent in (first, second)]
    try:
        await asyncio.wait_for(asyncio.gather(first.entered.wait(), second.entered.wait()), 2)
        first.end('interrupted')
        second.end('max-tokens')
        first.end('completed', turn=1)
        second.end('interrupted', turn=1)
        first.release.set()
        second.release.set()
        assert await asyncio.wait_for(asyncio.gather(*pending), 2) == [
            {'stopReason': 'cancelled'}, {'stopReason': 'max_tokens'}]
        assert all(owned.inflight_prompt is None for owned in bridge.sessions.values())
    finally:
        first.release.set()
        second.release.set()
        await asyncio.gather(*pending, return_exceptions=True)
        await close_context(ctx)


@pytest.mark.asyncio
async def test_explicit_cancel_wins_after_late_completed_event_and_waits_for_idle():
    ctx, bridge, first, second = controlled_bridge()
    pending = asyncio.create_task(send(bridge, ctx, 'alpha'))
    try:
        await asyncio.wait_for(first.entered.wait(), 2)
        await bridge.cancel(ctx, {'sessionId': 'alpha'})
        first.end('completed')
        await asyncio.sleep(0)
        assert not pending.done()
        assert first.cancelled == [{'kind': 'user'}] and second.cancelled == []
        first.release.set()
        assert await asyncio.wait_for(pending, 2) == {'stopReason': 'cancelled'}
    finally:
        first.release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await close_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['enqueue', 'idle', 'turn', 'interval'])
async def test_prompt_failure_releases_only_its_owned_admission_slot(stage):
    ctx, bridge, first, second = controlled_bridge()
    first.release.set()
    error = RuntimeError(stage + ' failure')
    fault = None
    if stage == 'enqueue':
        first.enqueue_error = error
    elif stage == 'idle':
        first.idle_error = error
    elif stage == 'turn':
        fault = ctx.on('agent/inbox/claimed', lambda payload: first.end('error', error=error))
    else:
        fault = ctx.on('agent/inbox/claimed', lambda payload: ctx.emit('agent/error',
            {'agent': first, 'turn': 1, 'error': error}))
    try:
        with pytest.raises(RuntimeError, match=stage + ' failure'):
            await send(bridge, ctx, 'alpha')
        assert bridge.sessions['alpha'].inflight_prompt is None
        assert bridge.sessions['beta'].inflight_prompt is None
        first.enqueue_error = first.idle_error = None
        if fault:
            fault()
        ctx.on('agent/inbox/claimed', lambda payload: first.end('completed'))
        assert await send(bridge, ctx, 'alpha') == {'stopReason': 'end_turn'}
    finally:
        await close_context(ctx)


@pytest.mark.asyncio
async def test_claimed_turn_error_uses_durable_end_instead_of_interval_error():
    ctx, bridge, first, second = controlled_bridge()
    pending = asyncio.create_task(send(bridge, ctx, 'alpha'))
    try:
        await asyncio.wait_for(first.entered.wait(), 2)
        ctx.emit('agent/error', {'agent': first, 'turn': 2, 'error': RuntimeError('wrong error')})
        impostor = ControlledAgent(ctx, 'alpha')
        ctx.emit('agent/error', {'agent': impostor, 'turn': 1, 'error': RuntimeError('impostor')})
        first.end('max-tokens')
        first.release.set()
        assert await asyncio.wait_for(pending, 2) == {'stopReason': 'max_tokens'}
    finally:
        first.release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await close_context(ctx)


@pytest.mark.asyncio
async def test_canonical_profile_acp_prompt_claims_real_turn_and_releases_agent(tmp_path):
    home = tmp_path / 'home'
    profile = home / 'profiles' / 'acp-owned'
    init_profile(str(profile), [], 'startup')
    rows = [{'id': name, 'name': '@deepseek-ai/dsh-' + name} for name in
            ('session', 'tools', 'system-prompt', 'agent', 'agent-loop', 'acp')]
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    runtime = await run_profile({'profile': 'acp-owned', 'dshHome': str(home), 'args': [], 'waitForExit': False})
    ctx = runtime['ctx']
    bridge = next(entry for entry in ctx.get('loader').entries
                  if entry.options.get('name') == '@deepseek-ai/dsh-acp').fiber.plugin
    adapter = StrictMockLlmAdapter([{'text': 'owned answer'}])
    ctx.provide('llm', adapter)
    try:
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        assert await asyncio.wait_for(send(bridge, ctx, created['sessionId']), 5) == {'stopReason': 'end_turn'}
        agent = bridge.sessions[created['sessionId']].agent
        assert any(event['type'] == 'turn/end' for event in agent.session.events)
        assert agent.status == 'idle' and bridge.sessions[agent.session.id].inflight_prompt is None
        assert 'owned answer' in str(agent.session.events)
    finally:
        runtime['shutdown'].shutdown(0)
        await runtime['shutdown'].wait()
    assert bridge.closed and not bridge.sessions
