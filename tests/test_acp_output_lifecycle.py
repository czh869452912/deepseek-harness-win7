import asyncio
from types import SimpleNamespace

import pytest

from dsh.acp.session_runtime import AcpSession
from dsh.acp.server import AcpPlugin
from dsh.acp.model_control import AcpModelControl
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.model_selection import ModelSelection
from test_acp_model_output import ModelRuntime, ImageStore, image_block


class OwnedAgent:
    id = 'owned'

    def __init__(self):
        self.session = SimpleNamespace(id=self.id, request_context=lambda: None)
        self.messages = []
        self.cancelled = []
        self.idle = asyncio.Event()
        self.entered = asyncio.Event()
        self.record = None

    def followup(self, message):
        self.messages.append(message)
        self.record.on_inbox_claimed(message, 3)

    async def when_idle(self):
        self.entered.set()
        await self.idle.wait()

    def cancel(self, reason):
        self.cancelled.append(reason)


def runtime_fixture(notify):
    ctx = Context()
    model, agent = ModelRuntime(), OwnedAgent()
    ctx.provide('llm', model)
    ctx.provide('agents', SimpleNamespace(get=lambda identity: agent if identity == agent.id else None))
    async def dispose():
        pass
    control = AcpModelControl(model, ModelSelection('mock', 'first'))
    record = AcpSession(agent, dispose, control, ctx, notify)
    agent.record = record
    return ctx, record, agent


def assistant(content, turn=3):
    return {'type': 'assistant/message', 'data': {'turn': turn, 'message': {'id': 'answer', 'content': content}}}


def finish(record):
    record.on_session_event({'type': 'turn/end', 'data': {'turn': 3, 'reason': {'kind': 'completed'}}})


@pytest.mark.asyncio
async def test_prompt_waits_for_committed_semantic_output_and_blocks_new_prompt_until_delivery():
    entered, release = asyncio.Event(), asyncio.Event()
    notifications = []
    async def notify(value):
        entered.set()
        await release.wait()
        notifications.append(value)
    ctx, record, agent = runtime_fixture(notify)
    prompt = asyncio.create_task(record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'go'}]}, False))
    try:
        await agent.entered.wait()
        record.on_session_event(assistant([{'type': 'reasoning', 'text': 'thought'}, {'type': 'text', 'text': 'answer'}]))
        record.on_session_event({'type': 'tool/call', 'data': {'turn': 3, 'callId': 'call', 'name': 'echo', 'arguments': '{'}})
        finish(record)
        agent.idle.set()
        await entered.wait()
        assert not prompt.done()
        with pytest.raises(ValueError, match='already in flight'):
            await record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'late'}]}, False)
        release.set()
        assert await prompt == {'stopReason': 'end_turn'}
        assert [value['update']['sessionUpdate'] for value in notifications] == ['agent_thought_chunk', 'agent_message_chunk', 'tool_call']
        assert all(value['sessionId'] == agent.id for value in notifications)
        assert notifications[-1]['update']['rawInput'] == '{'
    finally:
        release.set()
        agent.idle.set()
        await asyncio.gather(prompt, return_exceptions=True)


@pytest.mark.asyncio
async def test_corrupt_assistant_image_fails_exact_prompt_and_next_turn_can_deliver():
    notifications = []
    ctx, record, agent = runtime_fixture(notifications.append)
    store = ImageStore()
    store.failure = RuntimeError('corrupt stored image')
    ctx.provide('attachments', store)
    pending = asyncio.create_task(record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'go'}]}, False))
    await agent.entered.wait()
    record.on_session_event(assistant([{'type': 'image', 'attachment': {'mediaType': 'image/png'}}]))
    finish(record)
    agent.idle.set()
    with pytest.raises(RuntimeError, match='assistant output delivery failed'):
        await pending
    assert record.inflight_prompt is None
    assert notifications == []
    agent.idle.clear()
    agent.entered.clear()
    next_prompt = asyncio.create_task(record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'retry'}]}, False))
    await agent.entered.wait()
    record.on_session_event(assistant([{'type': 'text', 'text': 'recovered'}]))
    finish(record)
    agent.idle.set()
    assert await next_prompt == {'stopReason': 'end_turn'}
    assert [value['update']['content']['text'] for value in notifications] == ['recovered']


@pytest.mark.asyncio
async def test_supplemental_tool_result_conversion_failure_does_not_fail_assistant_turn():
    notifications = []
    ctx, record, agent = runtime_fixture(notifications.append)
    pending = asyncio.create_task(record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'go'}]}, False))
    await agent.entered.wait()
    record.on_session_event({'type': 'tool/result', 'data': {'turn': 3, 'message': {'content': [
        {'type': 'tool-result', 'toolCallId': 'call', 'content': [{'type': 'image', 'attachment': {}}]}]}}})
    record.on_session_event(assistant([{'type': 'text', 'text': 'done'}]))
    finish(record)
    agent.idle.set()
    assert await pending == {'stopReason': 'end_turn'}
    assert [value['update']['sessionUpdate'] for value in notifications] == ['agent_message_chunk']


@pytest.mark.asyncio
async def test_cancelled_image_admission_reserves_slot_until_write_finishes_without_late_user_message():
    ctx, record, agent = runtime_fixture(lambda value: None)
    store = ImageStore()
    store.gate = asyncio.Event()
    ctx.provide('attachments', store)
    controller = AbortController()
    pending = asyncio.create_task(record.prompt(ctx, {'prompt': [image_block()]}, True, controller.signal))
    await store.entered.wait()
    controller.abort(RuntimeError('request cancelled'))
    await asyncio.sleep(0)
    assert not pending.done() and record.inflight_prompt is not None
    with pytest.raises(ValueError, match='already in flight'):
        await record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'late'}]}, False)
    store.gate.set()
    assert await pending == {'stopReason': 'cancelled'}
    assert agent.messages == [] and agent.cancelled == []


@pytest.mark.asyncio
async def test_cancelled_observer_cannot_release_slot_while_owned_agent_still_runs():
    ctx, record, agent = runtime_fixture(lambda value: None)
    pending = asyncio.create_task(record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'go'}]}, False))
    await agent.entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert record.inflight_prompt is not None
    assert agent.cancelled == [{'kind': 'user'}]
    agent.idle.set()
    await asyncio.wait_for(record.inflight_prompt['admission_done'].wait(), 1)
    for attempt in range(10):
        if record.inflight_prompt is None:
            break
        await asyncio.sleep(0)
    assert record.inflight_prompt is None


@pytest.mark.asyncio
async def test_disposed_owned_agent_is_rejected_before_message_is_queued():
    ctx, record, agent = runtime_fixture(lambda value: None)
    ctx.get('agents').get = lambda identity: None
    with pytest.raises(RuntimeError, match='disposed outside the bridge'):
        await record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'go'}]}, False)
    assert agent.messages == [] and record.inflight_prompt is None


@pytest.mark.asyncio
async def test_admission_snapshot_precedes_worker_scheduling_and_later_config_mutation():
    ctx, record, agent = runtime_fixture(lambda value: None)
    pending = asyncio.create_task(record.prompt(ctx, {'prompt': [{'type': 'text', 'text': 'go'}]}, False))
    try:
        await asyncio.sleep(0)
        assert record.inflight_prompt is not None
        await record.model_control.set('model', '["other","next"]')
        await agent.entered.wait()
        assert record.model_control.selection.current.to_dict() == {'provider': 'mock', 'model': 'first'}
        finish(record)
        agent.idle.set()
        assert await pending == {'stopReason': 'end_turn'}
        assert record.model_control.snapshot().to_dict() == {'provider': 'other', 'model': 'next'}
    finally:
        agent.idle.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_bridge_close_waits_for_committed_output_before_flush_and_disposal():
    entered, release = asyncio.Event(), asyncio.Event()
    order = []
    async def notify(value):
        entered.set()
        await release.wait()
        order.append('output')
    ctx, record, agent = runtime_fixture(notify)
    async def flush(session):
        order.append('flush')
    async def dispose():
        order.append('dispose')
    record.dispose_fn = dispose
    ctx.provide('sessions', SimpleNamespace(flush=flush))
    bridge = AcpPlugin()
    bridge.sessions[agent.id] = record
    prompt = asyncio.create_task(bridge.prompt(ctx, {'sessionId': agent.id, 'prompt': [{'type': 'text', 'text': 'go'}]}))
    closing = None
    try:
        await agent.entered.wait()
        record.on_session_event(assistant([{'type': 'text', 'text': 'answer'}]))
        finish(record)
        agent.idle.set()
        await entered.wait()
        closing = asyncio.create_task(bridge.close_session(ctx, {'sessionId': agent.id}))
        await asyncio.sleep(0)
        assert not closing.done() and not prompt.done() and order == []
        assert agent.cancelled == [{'kind': 'user'}]
        release.set()
        assert await prompt == {'stopReason': 'cancelled'}
        assert await closing == {}
        assert order == ['output', 'flush', 'dispose'] and not bridge.sessions
    finally:
        release.set()
        agent.idle.set()
        await asyncio.gather(*([prompt, closing] if closing is not None else [prompt]), return_exceptions=True)


@pytest.mark.asyncio
async def test_bridge_close_during_image_admission_never_queues_a_late_message():
    ctx, record, agent = runtime_fixture(lambda value: None)
    store = ImageStore()
    store.gate = asyncio.Event()
    ctx.provide('attachments', store)
    agent.idle.set()
    bridge = AcpPlugin()
    bridge.image_prompt_enabled = True
    bridge.sessions[agent.id] = record
    pending = asyncio.create_task(bridge.prompt(ctx, {'sessionId': agent.id, 'prompt': [image_block()]}))
    closing = None
    try:
        await store.entered.wait()
        closing = asyncio.create_task(bridge.close_session(ctx, {'sessionId': agent.id}))
        await asyncio.sleep(0)
        assert not closing.done() and record.inflight_prompt is not None
        store.gate.set()
        assert await pending == {'stopReason': 'cancelled'}
        assert await closing == {}
        assert agent.messages == [] and not bridge.sessions and agent.cancelled == [{'kind': 'user'}]
    finally:
        store.gate.set()
        await asyncio.gather(*([pending, closing] if closing is not None else [pending]), return_exceptions=True)
