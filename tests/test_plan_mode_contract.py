"""Pinned plan-mode boundaries, replay and live review ownership."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.interaction.commands import CommandsPlugin
from dsh.interaction.user_questions import UserQuestionError, UserQuestionsPlugin
from dsh.plan.plan_mode import PlanModePlugin
from dsh.session.projections import SessionProjectionsPlugin


async def bench(active=None):
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(AgentPlugin)
    fiber = await ctx.plugin(PlanModePlugin, dict(section='PLAN POLICY'))
    session = Session.create('plan-contract')
    agent = Agent(session=session, ctx=ctx, agent_id=session.id)
    ctx.get('agents').enter(agent)
    if active is not None:
        session.append('plan/mode', dict(active=active))
    return ctx, agent, fiber


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ('reject', 'abort', 'accepted'))
async def test_pending_selection_commits_only_at_accepted_live_step(kind):
    ctx, agent, fiber = await bench()
    try:
        agent.session.append('turn/start', dict(turn=0))
        plan = ctx.get('planMode')
        assert plan.set(agent, True) == 'queued'
        controller = AbortController()
        if kind == 'abort':
            controller.abort('cancelled')
        decision = dict(kind='reject', reason='policy') if kind == 'reject' else dict(kind='enter', messages=[])
        result = await ctx.waterfall('agent/pre-step', dict(agent=agent, signal=controller.signal), lambda: decision)
        assert result == decision
        assert plan.get(agent) == (dict(active=True) if kind == 'accepted' else dict(active=False, pending=True))
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_failed_plan_append_preserves_intent_and_retries_without_blocking_step(monkeypatch):
    ctx, agent, fiber = await bench()
    try:
        agent.session.append('turn/start', dict(turn=0))
        plan = ctx.get('planMode')
        plan.set(agent, True)
        append = agent.session.append
        def fail(event_type, *args, **kwargs):
            if event_type == 'plan/mode':
                raise OSError('backend gone')
            return append(event_type, *args, **kwargs)
        monkeypatch.setattr(agent.session, 'append', fail)
        decision = dict(kind='enter', messages=[])
        assert await ctx.waterfall('agent/pre-step', dict(agent=agent), lambda: decision) == decision
        assert plan.get(agent) == dict(active=False, pending=True)
        monkeypatch.setattr(agent.session, 'append', append)
        assert await ctx.waterfall('agent/pre-step', dict(agent=agent), lambda: decision) == decision
        assert plan.get(agent) == dict(active=True)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_entry_keeps_logged_state_and_no_notice():
    ctx, agent, fiber = await bench()
    try:
        agent.session.append('request/header', {})
        agent.session.append('turn/start', dict(turn=0))
        plan = ctx.get('planMode')
        assert plan.set(agent, True) == 'queued'
        assert plan.set(agent, False) == 'cancelled'
        decision = dict(kind='enter', messages=[])
        assert await ctx.waterfall('agent/pre-step', dict(agent=agent), lambda: decision) == decision
        assert plan.get(agent) == dict(active=False)
        assert not any(event['type'] == 'plan/mode' for event in agent.session.events)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', (
    dict(answers=[]),
    dict(answers=[dict(id='other', selected=['Approve'])]),
    dict(answers=[dict(id='plan-review', selected=['Keep planning'])]),
    dict(answers=[dict(id='plan-review', selected=['Approve'], custom='')]),
    dict(answers=[dict(id='plan-review', selected=['Approve'], custom='change it')]),
    dict(answers=[dict(id='plan-review', selected=['Approve', 'Keep planning'])]),
    dict(answers=[dict(id='plan-review', selected=['Approve'])] * 2),
))
async def test_review_accepts_only_one_exact_approval(answer):
    ctx, agent, fiber = await bench(True)
    try:
        await ctx.plugin(UserQuestionsPlugin)
        ctx.on('user-questions/request', lambda request, next_fn=None: answer)
        result = await ctx.get('tools').execute(dict(name='exit_plan_mode', arguments=dict(plan='# Plan\nComplete.'), agent=agent))
        assert result.is_error
        assert 'keep planning' in result.content[0]['text']
        assert ctx.get('planMode').get(agent) == dict(active=True)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ('ASK_CANCELLED', 'ASK_ABORTED'))
async def test_review_dismissal_and_abort_keep_plan_state_and_first_outcome(code):
    ctx, agent, fiber = await bench(True)
    try:
        await ctx.plugin(UserQuestionsPlugin)
        original = UserQuestionError('review aborted', code)
        def answer(request, next_fn=None):
            raise original
        ctx.on('user-questions/request', answer)
        plan = ctx.get('planMode')
        with pytest.raises(Exception) as caught:
            await plan.handle_exit_plan_mode(dict(plan='# Plan'), exec_input=SimpleNamespace(agent=agent, signal=AbortController().signal))
        if code == 'ASK_ABORTED':
            assert caught.value is original
        else:
            assert str(caught.value) == 'The user dismissed the plan review to speak instead; stay in plan mode, stop here, and wait for their message.'
        assert plan.get(agent) == dict(active=True)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_missing_review_channel_cannot_approve():
    ctx, agent, fiber = await bench(True)
    try:
        with pytest.raises(RuntimeError, match='no user-questions channel'):
            await ctx.get('planMode').handle_exit_plan_mode(dict(plan='# Plan'), agent=agent)
        assert ctx.get('planMode').get(agent) == dict(active=True)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_disposed_service_cannot_approve_a_deferred_review():
    ctx, agent, fiber = await bench(True)
    plan = ctx.get('planMode')
    await ctx.plugin(UserQuestionsPlugin)
    reached = asyncio.Event()
    answer = asyncio.get_running_loop().create_future()
    async def review(request, next_fn=None):
        reached.set()
        return await answer
    ctx.on('user-questions/request', review)
    pending = asyncio.create_task(plan.handle_exit_plan_mode(dict(plan='# Plan'), agent=agent))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        await fiber.dispose()
        answer.set_result(dict(answers=[dict(id='plan-review', selected=['Approve'])]))
        with pytest.raises(RuntimeError, match='service was reloaded'):
            await pending
        assert plan.get(agent) == dict(active=True)
        assert ctx.get('planMode') is None
        assert ctx.get('tools').get('exit_plan_mode') is None
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await fiber.dispose()


@pytest.mark.asyncio
async def test_approval_is_typed_silent_pending_exit_until_next_step():
    ctx, agent, fiber = await bench(True)
    try:
        await ctx.plugin(UserQuestionsPlugin)
        captured = []
        def review(request, next_fn=None):
            captured.append(request)
            return dict(answers=[dict(id='plan-review', selected=['Approve'])])
        ctx.on('user-questions/request', review)
        result = await ctx.get('tools').execute(dict(name='exit_plan_mode', arguments=dict(plan='# Plan\nComplete.'), agent=agent))
        assert not result.is_error and result.value == dict(approved=True)
        assert captured[0]['questions'][0]['detail'] == '# Plan\nComplete.'
        assert captured[0]['questions'][0]['intent'] == dict(kind='plan-review', approve='Approve')
        plan = ctx.get('planMode')
        assert plan.get(agent) == dict(active=True, pending=False)
        assembly = await ctx.get('systemPrompt').assemble(dict(agent=agent, scope=agent))
        assert next(section['text'] for section in assembly['sections'] if section['name'] == 'plan:policy') == ''
        decision = dict(kind='enter', messages=[])
        assert await ctx.waterfall('agent/pre-step', dict(agent=agent), lambda: decision) == decision
        assert plan.get(agent) == dict(active=False)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_late_command_and_projection_mount_replay_and_dispose():
    ctx, agent, fiber = await bench()
    try:
        await ctx.plugin(SessionProjectionsPlugin)
        await ctx.plugin(CommandsPlugin)
        commands = ctx.get('commands')
        projections = ctx.get('sessionProjections')
        steered = []
        agent.steer = steered.append
        result = await commands.execute(agent, '/plan hello', [], AbortController().signal)
        assert result.result == dict(kind='success', text='Plan mode on. Use /plan off to leave.')
        assert steered[0]['content'] == [dict(type='text', text='hello')]
        replay = Session.create('cold-plan-command')
        replay.append('command/run', dict(name='plan', args='', commandId='enter'))
        assert projections.snapshot(replay)['values']['plan'] == dict(active=False, pending=True)
        replay.append('command/done', dict(commandId='enter', kind='success'))
        assert projections.snapshot(replay)['values']['plan'] == dict(active=False, pending=True)
        replay.append('plan/mode', dict(active=True))
        assert projections.snapshot(replay)['values']['plan'] == dict(active=True, pending=False)
        async def save_images(inputs):
            return [dict(attachmentId='owned-image', mediaType=item['mediaType'], bytes=1, width=1, height=1) for item in inputs]
        ctx.set_service('attachments', SimpleNamespace(save_images=save_images))
        images = [dict(data='YQ==', mediaType='image/png')]
        result = await commands.execute(agent, '/plan off', images, AbortController().signal)
        assert result.result == dict(kind='error', text='Image attachments cannot accompany /plan off.')
        assert ctx.get('planMode').get(agent) == dict(active=True)
        await fiber.dispose()
        assert projections.snapshot(replay)['values'] == {}
        assert await commands.execute(agent, '/plan', [], AbortController().signal) is None
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ('missing-wanted', 'extra-state', 'extra-running', 'invalid-wanted'))
async def test_plan_checkpoint_rejects_invalid_v2_state(damage):
    ctx, agent, fiber = await bench()
    try:
        await ctx.plugin(SessionProjectionsPlugin)
        registry = ctx.get('sessionProjections')
        checkpoint = registry.checkpoint(agent.session)
        assert checkpoint['plan']['ver'] == 2
        damaged = copy.deepcopy(checkpoint)
        state = damaged['plan']['val']
        if damage == 'missing-wanted':
            del state['wanted']
        elif damage == 'extra-state':
            state['extra'] = 1
        elif damage == 'extra-running':
            state['running'] = dict(commandId='owned', wanted=True, extra=1)
        else:
            state['wanted'] = 1
        with pytest.raises(ValueError):
            registry.restore(damaged, [], 0, agent.session.header)
        assert registry.restore(checkpoint, [], 0, agent.session.header)['snapshot']['values']['plan'] == dict(active=False, pending=False)
    finally:
        await fiber.dispose()
