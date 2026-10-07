import asyncio

import pytest

from dsh.compaction.engine import CompactionBasicPlugin
from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.agent import AgentPlugin
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.llm.llm_service import LlmError
from dsh.llm.token_meter import TokenMeterPlugin


class Model:
    provider, model = 'fixture', 'fixture'

    def __init__(self, delivery):
        self.delivery, self.requests, self.summary_requests = delivery, [], []

    async def resolve_model_info(self, provider, model, signal=None):
        return dict(provider=provider, id=model, name=model, context=dict(contextWindow=100000))

    async def stream(self, request):
        self.summary_requests.append(request)
        yield dict(type='text-delta', index=0, text='RECOVERY CHECKPOINT')
        yield dict(type='finish', reason=dict(kind='stop'))

    async def chat_completion_stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            if self.delivery == 'thrown':
                raise LlmError('request too large', 'CONTEXT_WINDOW_EXCEEDED')
            yield dict(type='text-delta', index=0, text='unaccepted partial')
            yield dict(type='finish', reason=dict(kind='error', failure=dict(message='request too large', code='CONTEXT_WINDOW_EXCEEDED')))
            return
        yield dict(type='text-delta', index=0, text='recovered')
        yield dict(type='finish', reason=dict(kind='stop'))


@pytest.mark.asyncio
@pytest.mark.parametrize('delivery', ['thrown', 'in-band'])
async def test_real_loop_overflow_rebuilds_same_step_from_replacement(delivery):
    ctx = Context()
    model = Model(delivery)
    ctx.set_service('llm', model)
    for plugin in (SessionPlugin, ToolsPlugin, SystemPrompt, AgentPlugin, AgentLoopPlugin, TokenMeterPlugin):
        await ctx.plugin(plugin)
    await ctx.plugin(CompactionBasicPlugin, dict(thresholdRatio=1, retainTokens=0, maxTokens=64))
    handle = await ctx.get('agent_loop').create('overflow-' + delivery)
    try:
        session = handle.agent.session
        session.append('turn/start', dict(turn=1))
        session.append_user_message('OLD HISTORY SENTINEL ' * 300)
        session.append('turn/end', dict(turn=1, reason=dict(kind='completed')))
        handle.agent.followup('continue from history')
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        assert len(model.requests) == 2 and len(model.summary_requests) == 1
        assert 'OLD HISTORY SENTINEL' in str(model.requests[0]['messages'])
        assert 'OLD HISTORY SENTINEL' not in str(model.requests[1]['messages'])
        assert 'RECOVERY CHECKPOINT' in str(model.requests[1]['messages'])
        assert session.events[-1]['data']['reason'] == dict(kind='completed')
        assert session.surface.replace_generation == 1
        assert [e['type'] for e in session.events if e['type'].startswith('compaction/')] == ['compaction/start', 'compaction/summary', 'compaction/end']
        assert len([e for e in session.events if e['type'] == 'step/start']) == 1
        assert len([e for e in session.events if e['type'] == 'step/end']) == 1
        assert 'unaccepted partial' not in str(session.derive_messages())
        assert ctx.get('tokenMeter').measure(session)['totalTokens'] > 0
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('finish', ['error', 'aborted'])
async def test_unrecovered_in_band_failure_does_not_publish_success(finish):
    class FailureModel(Model):
        async def chat_completion_stream(self, *args, **kwargs):
            yield dict(type='text-delta', index=0, text='not accepted')
            yield dict(type='finish', reason=dict(kind=finish, failure=dict(message='provider failed', code='PROVIDER_FAILURE')))
    ctx = Context()
    ctx.set_service('llm', FailureModel('in-band'))
    for plugin in (SessionPlugin, ToolsPlugin, SystemPrompt, AgentPlugin, AgentLoopPlugin):
        await ctx.plugin(plugin)
    handle = await ctx.get('agent_loop').create('failed-' + finish)
    try:
        handle.agent.followup('question')
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        events = handle.agent.session.events
        assert events[-1]['data']['reason']['kind'] == 'error'
        assert not any(e['type'] == 'assistant/message' for e in events)
        assert any(e['type'] == 'assistant/chunk' for e in events)
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()
