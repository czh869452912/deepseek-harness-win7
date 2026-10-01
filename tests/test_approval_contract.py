"""Public approval contracts derived from the pinned user-approval source.

These exercise real Cordis, native cancellation, and Session commit boundaries;
the upstream source suite runs independently through vitest.approval.config.mts.
"""

import asyncio
import uuid

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController, AbortSignal
from dsh.core.scope import create_scope, carrier_key_of
from dsh.core.session import Session, SessionStore
from dsh.core.system_prompt.service import SystemPrompt
from dsh.interaction.user_approval import (
    ApprovalService, UserApprovalPlugin, ASK_SENTENCE, NEVER_SENTENCE,
    set_approval_policy,
)


class AgentView:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def agent_for(name='approval-contract'):
    session = Session(name)
    session.append('turn/start', {'turn': 1})
    return AgentView(id=name, session=session)


def audit(agent):
    return [event for event in agent.session.events if event['type'].startswith('approval/')]


@pytest.mark.asyncio
@pytest.mark.parametrize('late', ['allowed-once', 'rejected', 'error'])
async def test_abort_settles_before_answer_and_consumes_late_result(late):
    ctx = Context()
    service = ApprovalService(ctx)
    agent, controller = agent_for(), AbortController()
    loop = asyncio.get_running_loop()
    entered, answer, drained = loop.create_future(), loop.create_future(), loop.create_future()
    errors = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    async def answerer(req, next_fn):
        entered.set_result(req)
        try:
            return await answer
        finally:
            drained.set_result(None)

    ctx.on('approval/request', answerer)
    request = dict(agent=agent, toolName='pwsh', signal=controller.signal)
    pending = asyncio.create_task(service.request(request))
    try:
        assert await asyncio.wait_for(entered, 1) is request
        controller.abort('user cancelled')
        done, _ = await asyncio.wait([pending], timeout=0.25)
        assert pending in done, 'abort must settle while the answerer is still waiting'
        assert pending.result() == 'cancelled'
        assert not answer.done(), 'the seam borrows the answerer; abort must not cancel it'
        before = audit(agent)
        assert [event['type'] for event in before] == ['approval/asked', 'approval/decided']
        assert before[1]['data'] == dict(id=before[0]['data']['id'], outcome='cancelled')
        assert not controller.signal._listeners
        if late == 'error':
            answer.set_exception(RuntimeError('late transport failure'))
        else:
            answer.set_result(late)
        await asyncio.wait_for(drained, 1)
        # Drain task normalization and completion callbacks, not elapsed time.
        for _ in range(4):
            await asyncio.sleep(0)
        assert audit(agent) == before
        assert not errors
    finally:
        if not answer.done():
            answer.set_result('rejected')
        await asyncio.gather(pending, return_exceptions=True)
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_falsey_preaborted_signal_precedes_policy_and_dispatch():
    class FalseySignal(AbortSignal):
        def __bool__(self):
            return False

    ctx = Context()
    service = ApprovalService(ctx, {'policy': 'never'})
    heard = []
    ctx.on('approval/request', lambda *_args: heard.append(True) or 'allowed-once')
    signal = FalseySignal.abort(None)
    agent = agent_for()
    assert await service.request(dict(agent=agent, toolName='pwsh', signal=signal)) == 'cancelled'
    assert not heard
    assert len(audit(agent)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['allowed-once', 'rejected', 'cancelled', 'unavailable'])
async def test_answer_wins_then_later_abort_cannot_change_audit(outcome):
    ctx = Context()
    service = ApprovalService(ctx)
    agent, controller = agent_for(), AbortController()
    ctx.on('approval/request', lambda *_args: outcome)
    assert await service.request(dict(agent=agent, toolName='pwsh', signal=controller.signal)) == outcome
    before = audit(agent)
    assert not controller.signal._listeners
    controller.abort()
    assert audit(agent) == before
    assert before[1]['data']['outcome'] == outcome


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['sync', 'async', 'rogue'])
async def test_answerer_failures_are_contained_and_audited(kind):
    ctx = Context()
    service = ApprovalService(ctx)
    agent = agent_for()

    def sync(req, next_fn):
        raise RuntimeError('sync failure')

    async def asynchronous(req, next_fn):
        raise RuntimeError('async failure')

    ctx.on('approval/request', sync if kind == 'sync' else asynchronous if kind == 'async' else lambda *_args: {'outcome': 'allowed-once'})
    assert await service.request(dict(agent=agent, toolName='pwsh', signal=AbortController().signal)) == 'unavailable'
    assert audit(agent)[1]['data']['outcome'] == 'unavailable'


@pytest.mark.asyncio
async def test_dispatch_borrows_request_and_routes_only_matching_scope():
    ctx = Context()
    service = ApprovalService(ctx)
    # Hashable stand-ins carry exact Agent identity, without a copied request.
    class BorrowedAgent:
        pass
    agents = [BorrowedAgent(), BorrowedAgent()]
    for index, agent in enumerate(agents):
        agent.session = agent_for('scoped-' + str(index)).session
    scopes = [create_scope(ctx, agent) for agent in agents]
    heard = []
    requests = [dict(agent=agent, toolName='pwsh') for agent in agents]

    def global_listener(req, next_fn):
        heard.append('global')
        return next_fn()

    ctx.on('approval/request', global_listener)
    for index, scope in enumerate(scopes):
        def listener(req, next_fn, caller_ctx=None, index=index):
            assert req is requests[index]
            assert carrier_key_of(caller_ctx) is agents[index]
            heard.append(index)
            return next_fn()
        scope.ctx.on('approval/request', listener)
    try:
        for request in requests:
            assert await service.request(request) == 'unavailable'
        assert heard == ['global', 0, 'global', 1]
    finally:
        for scope in scopes:
            await scope.dispose()


@pytest.mark.asyncio
async def test_policy_prompt_late_provider_and_service_disposal():
    ctx = Context()
    approval = await ctx.plugin(UserApprovalPlugin)
    assert ctx.get('approval') is not None
    prompt_fiber = await ctx.plugin(SystemPrompt)
    agent = agent_for()

    async def current(agent=None):
        assembled = await ctx.get('systemPrompt').assemble({} if agent is None else {'agent': agent})
        return [entry for entry in assembled['contexts'] if entry['name'] == 'approval:policy']

    try:
        assert (await current(agent))[0]['text'] == ASK_SENTENCE
        assert (await current())[0]['text'] == ''
        set_approval_policy(agent.session, 'never')
        first = await current(agent)
        assert first[0]['text'] == NEVER_SENTENCE
        assert await current(agent) == first
        await approval.dispose()
        assert ctx.get('approval') is None
        assert await current(agent) == []
    finally:
        await approval.dispose()
        await prompt_fiber.dispose()


@pytest.mark.asyncio
async def test_prompt_provider_reload_rebinds_without_duplicate_contributions():
    ctx = Context()
    prompt_fiber = await ctx.plugin(SystemPrompt)
    approval = await ctx.plugin(UserApprovalPlugin)
    agent = agent_for()
    try:
        await prompt_fiber.dispose()
        prompt_fiber = await ctx.plugin(SystemPrompt)
        assembled = await ctx.get('systemPrompt').assemble({'agent': agent})
        entries = [entry for entry in assembled['contexts'] if entry['name'] == 'approval:policy']
        assert len(entries) == 1
        assert entries[0]['text'] == ASK_SENTENCE
    finally:
        await approval.dispose()
        await prompt_fiber.dispose()


def test_policy_switch_publishes_one_identified_user_message():
    ctx = Context()
    service = ApprovalService(ctx)
    agent = agent_for()
    messages = []
    agent.inject = messages.append
    service.set_policy(agent, 'never')
    service.set_policy(agent, 'never')
    assert len(messages) == 1
    message = messages[0]
    assert message['id']
    assert message['role'] == 'user'
    assert message['source'] == dict(kind='plugin', plugin='user-approval')
    assert message['content'] == [dict(type='text', text='The approval policy changed from "ask" to "never" (changed by the user).')]


@pytest.mark.asyncio
async def test_audit_identity_is_fresh_uuid_and_absent_optional_fields_are_omitted():
    ctx = Context()
    service = ApprovalService(ctx)
    agent = agent_for()
    for _ in range(2):
        assert await service.request(dict(agent=agent, toolName='pwsh')) == 'unavailable'
    asked = [event['data'] for event in audit(agent) if event['type'] == 'approval/asked']
    assert asked[0]['id'] != asked[1]['id']
    for event in asked:
        assert set(event) == {'id', 'toolName'}
        assert str(uuid.UUID(event['id'])) == event['id']


@pytest.mark.asyncio
@pytest.mark.parametrize('event_type', ['approval/asked', 'approval/decided'])
async def test_real_session_contains_post_commit_observer_failure(event_type):
    ctx = Context()
    await ctx.plugin(SessionStore)
    service = ApprovalService(ctx)
    session = ctx.get('sessions').create('observer-' + event_type.split('/')[1])
    session.append('turn/start', {'turn': 1})
    agent = AgentView(session=session)
    observed = []

    def observer(_session, event):
        if event['type'] == event_type:
            observed.append(event)
            raise RuntimeError('observer failed after commit')

    ctx.on('session/event', observer)
    ctx.on('approval/request', lambda *_args: 'allowed-once')
    assert await service.request(dict(agent=agent, toolName='pwsh')) == 'allowed-once'
    assert len(observed) == 1
    assert [event['type'] for event in audit(agent)] == ['approval/asked', 'approval/decided']


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_at', ['approval/asked', 'approval/decided'])
async def test_precommit_append_failure_propagates_exact_error(fail_at):
    ctx = Context()
    service = ApprovalService(ctx)
    session = agent_for().session
    append = session.append
    failure = RuntimeError('append did not commit')
    heard = []

    def failing_append(event_type, data):
        if event_type == fail_at:
            raise failure
        return append(event_type, data)

    session.append = failing_append
    ctx.on('approval/request', lambda *_args: heard.append(True) or 'allowed-once')
    with pytest.raises(RuntimeError) as raised:
        await service.request(dict(agent=AgentView(session=session), toolName='pwsh'))
    assert raised.value is failure
    assert bool(heard) == (fail_at == 'approval/decided')


@pytest.mark.asyncio
@pytest.mark.parametrize('register_first', [False, True])
async def test_never_policy_cannot_be_bypassed_by_prepended_answerer(register_first):
    ctx = Context()
    consulted = []
    def grant(*_args):
        consulted.append(True)
        return 'allowed-once'
    if register_first:
        ctx.on('approval/request', grant, prepend=True)
    fiber = await ctx.plugin(UserApprovalPlugin, {'policy': 'never'})
    try:
        if not register_first:
            ctx.on('approval/request', grant, prepend=True)
        agent = agent_for()
        assert await ctx.get('approval').request(dict(agent=agent, toolName='pwsh')) == 'rejected'
        assert not consulted
        set_approval_policy(agent.session, 'ask')
        assert await ctx.get('approval').request(dict(agent=agent, toolName='pwsh')) == 'allowed-once'
        set_approval_policy(agent.session, 'never')
        assert await ctx.get('approval').request(dict(agent=agent, toolName='pwsh')) == 'rejected'
        assert len(consulted) == 1
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_single_answer_slot_delegation_and_listener_disposal():
    ctx = Context()
    service = ApprovalService(ctx)
    agent = agent_for()
    heard = []
    def delegate(req, next_fn):
        heard.append('delegate')
        return next_fn()
    ctx.on('approval/request', delegate)
    fiber = await ctx.plugin(lambda scope: scope.on('approval/request', lambda *_args: 'allowed-once'))
    ctx.on('approval/request', lambda *_args: heard.append('second') or 'rejected')
    assert await service.request(dict(agent=agent, toolName='pwsh')) == 'allowed-once'
    assert heard == ['delegate']
    await fiber.dispose()
    assert await service.request(dict(agent=agent, toolName='pwsh')) == 'rejected'
    assert heard == ['delegate', 'delegate', 'second']


@pytest.mark.asyncio
async def test_config_validation_rejects_unknown_policy_before_mount():
    ctx = Context()
    with pytest.raises(Exception):
        await ctx.plugin(UserApprovalPlugin, {'policy': 'sometimes'})
    assert ctx.get('approval') is None
    fiber = await ctx.plugin(UserApprovalPlugin)
    try:
        assert ctx.get('approval').config['policy'] == 'ask'
    finally:
        await fiber.dispose()
