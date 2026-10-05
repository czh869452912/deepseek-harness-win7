import asyncio
import copy

import pytest

from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.agent import AgentPlugin
from dsh.core.session import SessionPlugin
from dsh.core.tools import ToolsPlugin
from dsh.settings.provider import SettingsProvider


class MemorySettings(SettingsProvider):
    def __init__(self, ctx=None, config=None):
        super().__init__(ctx)
        self.doc = {}

    def load(self):
        return copy.deepcopy(self.doc)

    async def _persist_section(self, namespace, section):
        self.doc[namespace] = copy.deepcopy(section)


@pytest.mark.parametrize('cap', [0, -1, 1.5, True, '2', float('nan'), float('inf')])
def test_direct_parallel_cap_rejects_invalid_numbers(cap):
    ctx = Context()
    with pytest.raises(ValueError, match='maxParallelToolCalls must be a positive integer'):
        AgentLoopService(ctx, {'maxParallelToolCalls': cap})


@pytest.mark.parametrize('config,expected', [({}, 10), ({'maxParallelToolCalls': 1}, 1),
                                          ({'maxParallelToolCalls': 2.0}, 2)])
def test_direct_parallel_cap_resolves_original_default_and_integer_numbers(config, expected):
    ctx = Context()
    loop = AgentLoopService(ctx, config)
    assert loop.config['maxParallelToolCalls'] == expected


@pytest.mark.asyncio
async def test_parallel_settings_layers_refuses_and_unloads_reversibly():
    ctx = Context()
    settings_fiber = await ctx.plugin(MemorySettings)
    loop_fiber = await ctx.plugin(AgentLoopPlugin, {'agents': [], 'maxParallelToolCalls': 4})
    loop = ctx.get('agentLoop')
    settings = ctx.get('settings')
    try:
        assert loop.config['maxParallelToolCalls'] == 4
        descriptor = next(row for row in settings.describe() if row['ns'] == 'agent-loop')
        assert list(descriptor['value']) == ['maxParallelToolCalls']
        await settings.update('agent-loop', {'maxParallelToolCalls': 1})
        assert loop.config['maxParallelToolCalls'] == 1
        assert loop.config['agents'] == []
        with pytest.raises((ValueError, TypeError)):
            await settings.update('agent-loop', {'maxParallelToolCalls': 0})
        assert loop.config['maxParallelToolCalls'] == 1
        await settings_fiber.dispose()
        assert loop.config['maxParallelToolCalls'] == 4
        replacement = await ctx.plugin(MemorySettings)
        await ctx.get('settings').update('agent-loop', {'maxParallelToolCalls': 2})
        assert loop.config['maxParallelToolCalls'] == 2
        await loop_fiber.dispose()
        assert not [row for row in ctx.get('settings').describe() if row['ns'] == 'agent-loop']
        await replacement.dispose()
    finally:
        await ctx.fiber.dispose()


class ToolModel:
    def __init__(self):
        self.requests = []

    def chat_completion_stream(self, request=None, **options):
        self.requests.append(dict(request or {}, **options))
        if len(self.requests) == 1:
            for index in range(12):
                yield {'type': 'block-start', 'index': index, 'blockType': 'tool-call'}
                yield {'type': 'block-end', 'index': index, 'block': {
                    'type': 'tool-call', 'id': 'call-' + str(index), 'name': 'gated',
                    'arguments': '{"index":' + str(index) + '}'}}
            yield {'type': 'finish', 'reason': {'kind': 'tool-calls'}}
        else:
            yield {'type': 'block-end', 'index': 0, 'block': {'type': 'text', 'text': 'done'}}
            yield {'type': 'finish', 'reason': {'kind': 'stop'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('cap', [1, 2, 10])
async def test_factory_model_turn_honors_configured_parallel_pool(cap):
    ctx = Context()
    model = ToolModel()
    ctx.set_service('llm', model)
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin, {'agents': [], 'maxParallelToolCalls': cap})
    handle = await ctx.get('agents').create(session_id='pool-' + str(cap))
    entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak = 0
    started = []

    async def body(arguments, execution):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.append(arguments['index'])
        if len(started) == cap:
            entered.set()
        try:
            await release.wait()
            return 'done-' + str(arguments['index'])
        finally:
            active -= 1

    ctx.get('tools').register({
        'name': 'gated', 'description': 'gated', 'parameters': {
            'type': 'object', 'properties': {'index': {'type': 'number'}},
            'required': ['index'], 'additionalProperties': False},
        'isConcurrencySafe': lambda *arguments: True, 'execute': body,
        'output': {'schema': {'type': 'string'}, 'render': lambda arguments, value: [{'type': 'text', 'text': value}]},
    })
    try:
        handle.agent.followup({'content': [{'type': 'text', 'text': 'go'}], 'source': {'kind': 'user'}})
        try:
            await asyncio.wait_for(entered.wait(), 3)
        except asyncio.TimeoutError:
            pytest.fail(repr({'requests': model.requests, 'started': started, 'events': handle.agent.session.events}))
        release.set()
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        assert peak == cap
        assert started == list(range(12))
        assert len(model.requests) == 2
        results = [event for event in handle.agent.session.events if event['type'] == 'tool/result']
        assert [event['data']['message']['source']['callId'] for event in results] == ['call-' + str(index) for index in range(12)]
        assert all(not event['data']['message']['content'][0]['isError'] for event in results)
    finally:
        release.set()
        await handle.dispose()
        await ctx.fiber.dispose()
