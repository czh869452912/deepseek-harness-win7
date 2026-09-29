import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.scope import create_scope, scope_target
from dsh.typert.api_remotes import ApiRemotesPlugin
from dsh.typert.gateway import TypertGatewayService
from dsh.typert.registry import TypertRegistry


@pytest.mark.asyncio
async def test_real_cordis_events_bridge_to_gateway_and_delegate_by_scope():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    gateway_fiber = await ctx.plugin(TypertGatewayService)
    gateway = ctx.get('typertGateway')
    plugin = await ctx.plugin(ApiRemotesPlugin)
    class Subject:
        pass
    agent = Subject()
    scope = create_scope(ctx, agent)
    agent.ctx = scope.ctx
    ctx.get('typert').contexts.registerHost('agent', SimpleNamespace(wire='agentId', wireTypeSymbol='AgentId',
        identity=lambda value: 'agent-1' if value is agent.ctx else None, resolve=lambda _: agent.ctx))
    stream = gateway.events.open({'args': {}}, AbortController().signal)
    try:
        ready = await stream.__anext__()
        ctx.emit('api-session/status', 'agent-1', True)
        assert await asyncio.wait_for(stream.__anext__(), 2) == dict(type='emit', event='api-session/status', args=['agent-1', True])
        calls = []
        async def fallback(request, next_fn):
            calls.append(request)
            return {'handled': 'fallback'}
        ctx.on('approval/request', fallback)
        request = dict(agent=agent, signal=AbortController().signal, title='May I proceed?')
        pending = asyncio.create_task(ctx.waterfall(scope_target(None, agent), 'approval/request', request))
        frame = await asyncio.wait_for(stream.__anext__(), 2)
        assert frame['type'] == 'waterfall' and frame['agentId'] == 'agent-1'
        assert frame['request'] == {'title': 'May I proceed?'}
        gateway.events.result({'args': dict(clientId=ready['clientId'], eventId=frame['eventId'], outcome={'kind': 'next'})})
        assert await asyncio.wait_for(pending, 2) == {'handled': 'fallback'}
        assert calls == [request]
        pending = asyncio.create_task(ctx.waterfall(scope_target(None, agent), 'approval/request', request))
        frame = await asyncio.wait_for(stream.__anext__(), 2)
        gateway.events.result({'args': dict(clientId=ready['clientId'], eventId=frame['eventId'], outcome={'kind': 'result', 'value': {'allow': True}})})
        assert await pending == {'allow': True} and len(calls) == 1
        await plugin.dispose()
        assert gateway.events.registration is None
    finally:
        await stream.aclose()
        await scope.dispose()
        await ctx.fiber.dispose()
