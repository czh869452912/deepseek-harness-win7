import asyncio
from types import SimpleNamespace
import pytest


@pytest.mark.asyncio
async def test_failed_idle_scope_checkpoint_and_close_all_settle_before_detach(tmp_path):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.cordis.errors import AggregateError
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    class Store(Plugin):
        def apply(self, ctx): CurrentSessionStore(ctx, 4)
    class Projections(Plugin):
        def apply(self, ctx): SessionProjectionRegistry(ctx, 4)
    ctx = Context()
    for plugin in (CurrentLlmRuntime, Store, Projections, CurrentSystemPrompt, CurrentToolsPlugin,
                   NativeToolExecutorPlugin, CurrentAgentPlugin):
        await ctx.plugin(plugin)
    await ctx.plugin(CurrentJsonlSessionPersistencePlugin, dict(root=str(tmp_path), compression='none'))
    await ctx.plugin(CurrentAgentLoopPlugin, dict(agents=[]))
    handle = await ctx.agents.create(dict(sessionId='owned'))
    factory = ctx.agentLoop
    tx = next(iter(factory._transactions))
    # V4's idle machine has no separate legacy driver. Exercise the Python
    # transaction's optional owned continuation as well as its real scope.
    tx.driver = asyncio.create_task(asyncio.Event().wait())
    factory._active_tasks.append(tx.driver)
    scope_dispose, writer_close = tx.scope.dispose, tx.stored['handle'].close
    failures = [RuntimeError(name) for name in ('idle', 'scope', 'cache', 'close')]
    trace, entered, release = [], asyncio.Event(), asyncio.Event()
    async def idle():
        trace.append('idle')
        raise failures[0]
    async def scope():
        trace.append('scope')
        await scope_dispose()
        raise failures[1]
    async def cache(session):
        assert session is handle.agent.session
        trace.append('cache')
        raise failures[2]
    async def close():
        trace.append('close')
        entered.set()
        await release.wait()
        await writer_close()
        raise failures[3]
    handle.agent.when_idle = idle
    tx.scope.dispose = scope
    tx.stored['handle'].close = close
    ctx.set_service('sessionProjectionCache', SimpleNamespace(drain=cache))
    first = asyncio.ensure_future(handle.dispose())
    second = asyncio.ensure_future(handle.dispose())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert tx.driver.done() and tx.driver not in factory._active_tasks
        assert ctx.agents.get('owned') is handle.agent
        assert ctx.sessions.get('owned') is handle.agent.session
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert isinstance(results[0], AggregateError)
        assert results[0] is results[1]
        assert results[0].errors == failures
        assert trace == ['idle', 'scope', 'cache', 'close']
        assert ctx.agents.get('owned') is None and ctx.sessions.get('owned') is None
        assert not ctx.sessionPersistence.tracker.writers
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await ctx.fiber.dispose()
