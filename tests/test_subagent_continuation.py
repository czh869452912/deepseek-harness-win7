import asyncio

import pytest

from dsh.core.abort import AbortController
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
from dsh.session.session_query import SessionQueryService
from dsh.subagent.continuation import ContinuationManager
from dsh.subagent.setup_registry import SetupRegistry
from dsh.subagent.runtime import SubagentRuntime
from dsh.subagent.in_process import InProcessProvider
from dsh.subagent.errors import SubagentError
from test_subagent_in_process import setup


async def mounted(tmp_path):
    ctx, model, parent = await setup()
    await ctx.plugin(JsonlSessionPersistencePlugin, {'root': str(tmp_path)})
    ctx.set_service('sessionQuery', SessionQueryService(ctx, open_at='never'))
    runtime = SubagentRuntime(ctx)
    runtime.registerProvider(InProcessProvider('spawn'))
    manager = ContinuationManager(ctx, runtime, SetupRegistry())
    await manager.owner
    return ctx, model, parent, manager


async def retired(manager, sid):
    async def wait():
        while sid in manager.activations:
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_background_acceptance_natural_disposal_and_cold_followup(tmp_path):
    ctx, model, parent, manager = await mounted(tmp_path)
    signal = AbortController()
    try:
        first = await manager.start(dict(provider='spawn', label='worker', childId='worker', signal=signal.signal,
                                        request=dict(parent=parent.agent, prompt='first child task', persona='test persona')))
        assert first['childId'] == 'worker' and first['messageId']
        original = manager.activations['worker'].handle.agent
        signal.abort(ValueError('admission signal no longer owns child'))
        await retired(manager, 'worker')
        assert ctx.get('agents').get('worker') is None
        await parent.agent.when_idle()
        observation = await ctx.get('sessionQuery').observeSession('worker')
        assert observation.header.parentSession == parent.agent.id
        assert any(event['type'] == 'assistant/message' for event in observation.events)
        observation.dispose()
        message_id = await manager.followup(parent.agent, 'worker', 'second child task')
        restored = manager.activations['worker'].handle.agent
        assert restored is not original and message_id != first['messageId']
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        assert any('first child task' in str(req['messages']) and 'second child task' in str(req['messages']) for req in model.requests)
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()


class BlockingModel:
    provider, model = 'fixture', 'fixture'

    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.requests = []

    async def chat_completion_stream(self, messages, **kwargs):
        self.requests.append(messages)
        self.entered.set()
        await self.release.wait()
        yield {'choices': [{'delta': {'content': 'done'}, 'finish_reason': 'stop'}]}


@pytest.mark.asyncio
async def test_followups_use_one_live_fifo_and_reject_wrong_parent(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    model = BlockingModel()
    ctx.set_service('llm', model)
    stranger = await ctx.get('agents').create('stranger')
    try:
        await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='first')))
        await asyncio.wait_for(model.entered.wait(), 2)
        child = manager.activations['worker'].handle.agent
        second = await manager.followup(parent.agent, 'worker', 'second')
        third = await manager.followup(parent.agent, 'worker', 'third')
        assert second != third and manager.activations['worker'].handle.agent is child
        with pytest.raises(SubagentError) as error:
            await manager.followup(stranger.agent, 'worker', 'intruder')
        assert error.value.code == 'UNAUTHORIZED'
        model.release.set()
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        query = await ctx.get('sessionQuery').observeSession('worker')
        accepted = [event['data']['id'] for event in query.events if event['type'] == 'user/message']
        assert accepted.index(second) < accepted.index(third)
        assert 'intruder' not in str(query.events)
        query.dispose()
    finally:
        model.release.set()
        await manager.drain()
        await stranger.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_scoped_drain_waits_child_first_and_keeps_other_tree_open(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    model = BlockingModel()
    ctx.set_service('llm', model)
    other = await ctx.get('agents').create('other')
    released = []
    ctx.on('agent/disposed', lambda payload: released.append(payload['agent'].id))
    try:
        await manager.start(dict(provider='spawn', label='child', childId='child', request=dict(parent=parent.agent, prompt='child')))
        child = manager.activations['child'].handle.agent
        await manager.start(dict(provider='spawn', label='grandchild', childId='grandchild', request=dict(parent=child, prompt='grandchild')))
        await manager.drain_descendants([parent.agent])
        assert released.index('grandchild') < released.index('child')
        with pytest.raises(SubagentError, match='closed'):
            await manager.start(dict(provider='spawn', label='denied', request=dict(parent=parent.agent, prompt='denied')))
        await manager.start(dict(provider='spawn', label='allowed', childId='allowed', request=dict(parent=other.agent, prompt='allowed')))
        assert 'allowed' in manager.activations
        await manager.drain_children(other.agent, ['allowed', 'unknown'])
        await manager.start(dict(provider='spawn', label='again', childId='again', request=dict(parent=other.agent, prompt='again')))
        assert 'again' in manager.activations
    finally:
        model.release.set()
        await manager.drain()
        await other.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_parent_waits_for_child_settlement_and_report_does_not_finish_child(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    model = BlockingModel()
    ctx.set_service('llm', model)
    try:
        await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='work')))
        await asyncio.wait_for(model.entered.wait(), 2)
        child = manager.activations['worker'].handle.agent
        report = manager.report(child, [{'type': 'text', 'text': 'partial progress'}], {'delivery': 'quiet'})
        assert report and child.status == 'running' and parent.agent.status == 'idle'
        with pytest.raises(SubagentError):
            manager.interrupt('worker', {'kind': 'ancestor', 'agent': child})
        manager.interrupt('worker', {'kind': 'ancestor', 'agent': parent.agent})
        await retired(manager, 'worker')
        model.release.set()
        await parent.agent.when_idle()
        assert any('partial progress' in str(messages) for messages in model.requests)
    finally:
        model.release.set()
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_idle_parent_activation_waits_for_owned_descendant(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    worker_gate, grandchild_gate = asyncio.Event(), asyncio.Event()
    class RoutedModel:
        provider, model = 'fixture', 'fixture'
        async def chat_completion_stream(self, messages, **kwargs):
            # The spawn provider gives each child only its own prompt.
            gate = grandchild_gate if 'grandchild work' in str(messages) else worker_gate
            await gate.wait()
            yield {'choices': [{'delta': {'content': 'done'}, 'finish_reason': 'stop'}]}
    ctx.set_service('llm', RoutedModel())
    try:
        await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='worker work')))
        worker = manager.activations['worker'].handle.agent
        await manager.start(dict(provider='spawn', label='grandchild', childId='grandchild', request=dict(parent=worker, prompt='grandchild work')))
        worker_gate.set()
        await asyncio.wait_for(worker.when_idle(), 2)
        assert manager.state(manager.activations['worker']) == 'waiting'
        await manager.followup(parent.agent, 'worker', 'more work while waiting')
        assert manager.activations['worker'].handle.agent is worker
        await asyncio.wait_for(worker.when_idle(), 2)
        assert manager.state(manager.activations['worker']) == 'waiting'
        grandchild_gate.set()
        await retired(manager, 'worker')
        assert 'grandchild' not in manager.activations
    finally:
        worker_gate.set()
        grandchild_gate.set()
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cold_resume_uses_descriptor_after_provider_removal_and_stale_parent_rejected(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    try:
        await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='first')))
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        manager.host.providers.clear()
        await manager.followup(parent.agent, 'worker', 'provider need not be resident for resume')
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        stale = parent.agent
        await parent.dispose()
        parent = await ctx.get('agents').resume('parent')
        with pytest.raises(SubagentError) as error:
            await manager.followup(stale, 'worker', 'stale authority')
        assert error.value.code == 'UNAUTHORIZED'
        with pytest.raises(SubagentError):
            manager.interrupt('unknown', {'kind': 'ancestor', 'agent': stale})
        await manager.followup(parent.agent, 'worker', 'current parent incarnation')
        await retired(manager, 'worker')
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_revoked_setup_never_publishes_or_accepts_child(tmp_path):
    ctx, model, parent, manager = await mounted(tmp_path)
    removed = []
    def install(child_ctx):
        revoke()
        return lambda: removed.append(child_ctx.agent.id)
    revoke = manager.setups.register(install)
    try:
        with pytest.raises(SubagentError) as error:
            await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='never admitted')))
        assert error.value.code == 'ACTIVATION_SETUP_REVOKED'
        assert removed == ['worker']
        assert ctx.get('agents').get('worker') is None
        assert 'worker' not in manager.activations
        assert not model.requests
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()
