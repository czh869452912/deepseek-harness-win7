import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.core.system_prompt import SystemPrompt
from dsh.core.scope import scope_of
from dsh.core.abort import AbortController
from dsh.llm.llm_service import LlmRuntime
from dsh.subagent.runtime import SubagentPlugin
from dsh.subagent.model_selection import ModelSelectionSettings
from dsh.subagent.canonical_tools import CanonicalToolSubagent

time.time = lambda:1791244800
calls = [{}, dict(provider='alpha'), dict(provider='alpha',model='fast'), dict(provider='alpha',model='plain'),
    dict(provider='alpha',model='unlisted'), dict(provider='missing',model='hidden'), dict(provider='beta'),
    dict(model='fast'), dict(provider=''), dict(provider='alpha',model=''), dict(provider='alpha',model='outside')]


class Adapter:
    def provider_info(self, provider):
        return dict(id=provider,name=provider.upper()+' API')

    async def list_models(self, provider):
        return [dict(provider=provider,id='fast',name='Fast',description='Focused work.'),dict(provider=provider,id='plain',name='Plain')]

    async def resolve_model(self, provider, model, signal=None):
        return dict(provider=provider,id=model,name='Plain' if model=='plain' else 'Fast',
            **({} if model=='plain' else dict(description='Focused work.',reasoning=dict(efforts=[dict(id='low',name='Low'),dict(id='high',name='High',description='Quality first.')],defaultEffort='high'))))


async def forbidden(*args):
    raise RuntimeError('schema observer must not start a child')


async def main():
    rows = []
    for enabled in (False,True):
        for inherits in (False,True):
            for defaults in (False,True):
                for mode in ('one-shot','continuable'):
                    name = '/'.join([str(enabled).lower(),str(inherits).lower(),str(defaults).lower(),mode])
                    ctx, handle = Context(), None
                    try:
                        for provider in (LlmRuntime,SessionPlugin,ToolsPlugin,SystemPrompt,AgentPlugin):
                            await ctx.plugin(provider)
                        await ctx.plugin(AgentLoopPlugin,dict(agents=[]))
                        await ctx.plugin(SubagentPlugin)
                        await ctx.plugin(ModelSelectionSettings,dict(enabled=enabled,allowedModels=[dict(provider='alpha',model='fast'),dict(provider='alpha',model='plain'),dict(provider='alpha',model='unlisted'),dict(provider='missing',model='hidden')]))
                        ctx.get('llm').register_adapter(['alpha'],Adapter())
                        provider = SimpleNamespace(name='probe',inheritsParentContext=inherits,
                            capabilities=dict(agentOptions=True,depthLimit=True,outputSchema=True,toolFilter=True,persona=True),start=forbidden,prepareContinuable=forbidden)
                        if defaults:
                            provider.agentRouteDefaults = dict(provider='alpha',model='fast')
                        ctx.get('subagents').registerProvider(provider)
                        async def setup(agent_ctx):
                            await agent_ctx.plugin(CanonicalToolSubagent,dict(provider='probe',modelSelectionSettings=True,backgroundMode=mode))
                        handle = await ctx.get('agents').create(dict(sessionId='model-probe-'+name,agentOptions=dict(provider='alpha',model='fast'),setup=setup))
                        rows.append(dict(name=name+'/schema',schemas=ctx.get('tools').schemas(scope_of(handle.agent.ctx)),events=handle.agent.session.events))
                        if enabled:
                            for position,args in enumerate(calls):
                                result = await ctx.get('tools').execute(ToolExecutionInput(name='list_subagent_models',arguments=args,call_id='model-call-'+str(position),signal=AbortController().signal,agent=handle.agent))
                                public = dict(content=result.content,isError=result.is_error)
                                if not result.is_error:
                                    public["value"] = result.value
                                if result.error is not None:
                                    public['error'] = result.error
                                if result.meta is not None:
                                    public['meta'] = result.meta
                                if result.additional_contexts:
                                    public['additionalContexts'] = result.additional_contexts
                                if result.concludes_turn:
                                    public['concludesTurn'] = True
                                rows.append(dict(name=name+'/call/'+str(position),result=public))
                    finally:
                        if handle:
                            await handle.dispose()
                        await ctx.fiber.dispose()
    modules = {}
    for name,module in sorted(sys.modules.items()):
        filename = getattr(module,'__file__',None)
        if filename and (name=='dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            modules[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with Path(sys.argv[2]).open('x',encoding='utf-8') as stream:
        json.dump(dict(root=str(root),python=sys.version,executable=sys.executable,imports=modules,rows=rows,fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),stream,indent=2)
        stream.write('\n')


asyncio.run(main())
