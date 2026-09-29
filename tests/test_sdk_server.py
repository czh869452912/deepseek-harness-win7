import asyncio
import pytest

from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.tools import ToolsPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.notifications import emit_contained
from dsh.llm.llm_service import LlmRuntime
from dsh.sdk.server import HarnessSdkJsonRpcServer


class Peer:
    def __init__(self):
        self.notifications = []

    def notify(self, name, params):
        self.notifications.append((name, params))


class Adapter:
    def provider_info(self, provider):
        return dict(id=provider, name=provider)

    async def resolve_model(self, provider, model, signal=None):
        return dict(provider=provider, id=model, name=model, context=dict(contextWindow=10000))

    async def stream(self, request):
        yield dict(type='block-start', index=0, blockType='text')
        yield dict(type='text-delta', index=0, text='SDK answer')
        yield dict(type='block-end', index=0, block=dict(type='text', text='SDK answer'))
        yield dict(type='finish', reason=dict(kind='stop'))


async def setup():
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    ctx.get('llm').register_adapter(['fixture'], Adapter())
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(AgentLoopPlugin)
    peer = Peer()
    server = HarnessSdkJsonRpcServer(ctx, peer)
    await server.initialize(dict(cwd='.', provider='fixture', model='model'))
    return ctx, peer, server


@pytest.mark.asyncio
async def test_real_sdk_prompt_reuses_agent_preserves_message_identity_and_drains():
    ctx, peer, server = await setup()
    try:
        results = await asyncio.gather(*(server.prompt(dict(sessionId='sdk-session', contentBlocks=[dict(type='text', text=str(i))])) for i in range(2)))
        handle = server.sessions['sdk-session']
        await asyncio.wait_for(handle.agent.when_idle(), 5)
        assert len(ctx.get('agents').list()) == 1
        assert results[0]['messageId'] != results[1]['messageId']
        events = [payload['event'] for name, payload in peer.notifications if name == 'session.event']
        assert all(any(result['messageId'] in str(event) for event in events) for result in results)
        assert any('SDK answer' in str(event) for event in events)
        assert await asyncio.gather(server.shutdown(), server.shutdown()) == [{}, {}]
        assert ctx.get('agents').get('sdk-session') is None
        with pytest.raises(RuntimeError, match='shutting down'):
            await server.prompt(dict(sessionId='other', contentBlocks=[]))
    finally:
        await server.shutdown()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_sdk_rejects_retired_agent_and_uses_scoped_local_subagent_authority():
    ctx, peer, server = await setup()
    try:
        handle = await server.get_or_create('parent')
        info = dict(local=False, provider='remote', id='child', stopReason='completed')
        emit_contained(ctx, 'subagent/end', info, handle.agent, object())
        assert not any(name == 'subagent.finished' for name, _ in peer.notifications)
        emit_contained(ctx, 'subagent/end', dict(info, local=True, provider='spawn'), handle.agent, object())
        assert peer.notifications[-1] == ('subagent.finished', dict(provider='spawn', agentId='child', parentSessionId='parent', childSessionId='child', stopReason='completed', status='ok'))
        await handle.dispose()
        with pytest.raises(RuntimeError, match='disposed outside'):
            await server.prompt(dict(sessionId='parent', contentBlocks=[]))
    finally:
        await server.shutdown()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_sdk_shutdown_waits_for_pending_creation_and_disposes_its_result():
    ctx, peer, server = await setup()
    agents = ctx.get('agents')
    original = agents.create
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    agents.create = delayed
    try:
        pending = asyncio.create_task(server.get_or_create('racing'))
        await entered.wait()
        shutdown = asyncio.create_task(server.shutdown())
        await asyncio.sleep(0)
        assert not shutdown.done()
        release.set()
        await pending
        assert await shutdown == {}
        assert agents.get('racing') is None
    finally:
        release.set()
        await server.shutdown()
        await ctx.fiber.dispose()
