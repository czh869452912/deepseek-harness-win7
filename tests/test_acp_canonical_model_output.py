import asyncio
import copy

import pytest

from dsh.core.session import Session
from test_acp_model_output import ModelRuntime
from test_acp_session_controls import boot_profile, stop_profile, bridge_fixture, dispose_context
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter


class RoutedAdapter:
    def __init__(self):
        self.models = ModelRuntime()
        self.source = StrictMockLlmAdapter([
            {'reasoning': 'inspect', 'tool_calls': [{'id': 'echo-call', 'name': 'echo', 'arguments': '{}'}]},
            {'reasoning': 'done', 'text': 'first answer'},
            {'text': 'next answer'},
        ])
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def list_models(self, provider):
        return await self.models.list_models(provider)

    async def resolve_model(self, provider, model, signal=None):
        return await self.models.resolve_model_info(provider, model, signal)

    async def prepare_call(self, provider, model, signal=None):
        info = await self.resolve_model(provider, model, signal)
        async def stream(request):
            self.requests.append({key: copy.deepcopy(value) for key, value in request.items() if key != 'signal'})
            if len(self.requests) == 1:
                self.entered.set()
                await self.release.wait()
            async for chunk in self.source.chat_completion_stream(
                    request['messages'], request.get('tools'), request.get('system')):
                yield chunk
        return {'model': info, 'stream': stream}


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['jsonl', 'sqlite'])
async def test_canonical_multistep_turn_keeps_admitted_route_and_resume_never_replays_outputs(tmp_path, backend, monkeypatch):
    runtime, bridge, unused = await boot_profile(tmp_path, backend, monkeypatch)
    ctx = runtime['ctx']
    adapter = RoutedAdapter()
    ctx.get('llm').register_adapter(['mock', 'other'], adapter)
    notifications, executions = [], []
    bridge.config.update(provider='mock', model='first', notify=notifications.append)
    detach_tool = ctx.get('tools').register_tool('echo', 'Record real execution',
        {'type': 'object', 'properties': {}}, lambda args: executions.append(args) or 'executed')
    pending = None
    try:
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        assert created['configOptions'][0]['currentValue'] == '["mock","first"]'
        assert created['configOptions'][1]['currentValue'] == 'high'
        pending = asyncio.create_task(bridge.prompt(ctx, dict(created, prompt=[{'type': 'text', 'text': 'run echo'}])))
        await asyncio.wait_for(adapter.entered.wait(), 3)
        changed = await bridge.set_config_option(ctx, dict(created, configId='model', value='["other","next"]'))
        assert changed['configOptions'][0]['currentValue'] == '["other","next"]'
        await bridge.set_config_option(ctx, dict(created, configId='reasoning_effort', value='low'))
        adapter.release.set()
        assert await asyncio.wait_for(pending, 5) == {'stopReason': 'end_turn'}
        assert executions == [{}]
        assert [(request['provider'], request['model'], request['reasoningEffort']) for request in adapter.requests] == [
            ('mock', 'first', 'high'), ('mock', 'first', 'high')]
        agent = bridge.sessions[created['sessionId']].agent
        committed = [event for event in agent.session.events if event['type'] == 'assistant/message']
        assert {value['update']['messageId'] for value in notifications if 'messageId' in value['update']} == {
            event['data']['message']['id'] for event in committed}
        kinds = [value['update']['sessionUpdate'] for value in notifications]
        assert kinds == ['agent_thought_chunk', 'tool_call', 'tool_call_update', 'agent_thought_chunk', 'agent_message_chunk']
        assert all(value['sessionId'] == created['sessionId'] for value in notifications)
        count = len(notifications)
        bridge._on_session_event(Session(created['sessionId']), committed[-1])
        await bridge.sessions[created['sessionId']].drain_updates()
        assert len(notifications) == count
        assert await bridge.prompt(ctx, dict(created, prompt=[{'type': 'text', 'text': 'next route'}])) == {'stopReason': 'end_turn'}
        assert (adapter.requests[-1]['provider'], adapter.requests[-1]['model'], adapter.requests[-1]['reasoningEffort']) == ('other', 'next', 'low')
        await bridge.close_session(ctx, created)
        notifications.clear()
        resumed = await bridge.resume_session(ctx, dict(created, cwd=str(tmp_path)))
        assert resumed['configOptions'][0]['currentValue'] == '["other","next"]'
        assert resumed['configOptions'][1]['currentValue'] == 'low'
        await bridge.sessions[created['sessionId']].drain_updates()
        assert notifications == []
        await bridge.close_session(ctx, created)
    finally:
        adapter.release.set()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        detach_tool()
        await stop_profile(runtime)
    runtime, bridge, unused = await boot_profile(tmp_path, backend, monkeypatch)
    ctx = runtime['ctx']
    ctx.get('llm').register_adapter(['mock', 'other'], RoutedAdapter())
    notifications.clear()
    bridge.config.update(provider='mock', model='first', notify=notifications.append)
    try:
        resumed = await bridge.resume_session(ctx, dict(created, cwd=str(tmp_path)))
        assert [item['currentValue'] for item in resumed['configOptions']] == ['["other","next"]', 'low']
        assert notifications == []
    finally:
        await stop_profile(runtime)


@pytest.mark.asyncio
async def test_option_discovery_failure_rolls_back_owned_agent_before_materialization(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    model = ModelRuntime()
    model.available = False
    ctx.provide('llm', model)
    bridge.config.update(provider='mock', model='first')
    try:
        with pytest.raises(RuntimeError, match='route missing'):
            await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        assert factory.created == factory.disposed and not factory.live
        assert not bridge.sessions and not persistence.headers
    finally:
        await bridge.close(ctx)
        await dispose_context(ctx)
