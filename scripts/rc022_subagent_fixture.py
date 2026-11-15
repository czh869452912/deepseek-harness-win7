"""Owned actual v4 runtime used by candidate integration probes.

workingDirectory is an explicit controlled collaborator, not provider qualification.
"""
from types import SimpleNamespace as NS


async def setup(workspace,script=None):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    from dsh.session.query_current import CurrentSessionQueryService
    from dsh.subagent.service import SubagentPlugin
    from dsh.subagent.providers import SpawnInProcessPlugin
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context()
    try:
        for plugin in (CurrentLlmRuntime,Store,Projections,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):
            await ctx.plugin(plugin)
        await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(workspace),compression='none'))
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        ctx.get('llm').registerAdapter(['script'],ScriptAdapter(dict(script=['hang']*100 if script is None else script)))
        ctx.set_service('sessionQuery',CurrentSessionQueryService(ctx))
        async def ensure(agent,signal):return 'C:/rc022-work'
        async def directory(agent,path,signal):return path
        ctx.set_service('workingDirectory',NS(ensure=ensure,set=directory))
        await ctx.plugin(SubagentPlugin)
        provider=await ctx.plugin(SpawnInProcessPlugin)
        return NS(ctx=ctx,service=ctx.get('subagents'),provider=provider,signal=NEVER_ABORTED)
    except BaseException:
        await ctx.fiber.dispose();raise
