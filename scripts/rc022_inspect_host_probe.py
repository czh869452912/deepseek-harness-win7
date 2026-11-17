"""Actual shared Host registry with per-Agent current inspection tools."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.scope import create_scope
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.extensions.inspect_registry_current import CurrentCordisInspectRegistryService
    from dsh.extensions.inspect_providers_current import CurrentCordisInspectProviders,host_inspect_providers
    from dsh.extensions.inspect_tools_current import CurrentCordisInspectTools
    class Agent:pass
    ctx=Context();rows=[];scopes=[]
    try:
        await ctx.plugin(CurrentSystemPrompt);await ctx.plugin(CurrentToolsPlugin);await ctx.plugin(NativeToolExecutorPlugin)
        await ctx.plugin(CurrentCordisInspectRegistryService)
        host=await ctx.plugin(CurrentCordisInspectProviders)
        rows.append(dict(stage='mounted',providers=[row['id'] for row in ctx.cordisInspect.list()]))
        def definition(name):
            return dict(name=name,description='fixture '+name,parameters=dict(type='object',properties={}),
                execute=lambda *_:{},output=dict(schema=dict(type='object'),render=lambda *_:[]))
        ctx.tools.register(definition('global_fixture'))
        agents=[]
        for index in [0,1]:
            agent=Agent();agent.id='agent-'+str(index);scope=create_scope(ctx,agent);agent.ctx=scope.ctx;agents.append(agent);scopes.append(scope)
            await scope.ctx.plugin(CurrentCordisInspectTools)
        def private(owner):owner.tools.register(definition('private_fixture'))
        private.inject=['tools']
        await scopes[0].ctx.plugin(private)
        signal=AbortController().signal
        for agent in agents:
            value=await ctx.cordisInspect.query('host','Tool','listTools',{},agent,signal)
            rows.append(dict(stage='tool-view',agent=agent.id,tools=[row['name'] for row in value['tools']]))
        agent=agents[0];tool=ctx.tools.get('cordis_inspect_query',agent)
        value=await tool.handler(dict(platform='host',provider='Service',method='listService',input=dict(service='tools')),NS(agent=agent,signal=signal))
        rows.append(dict(stage='tool-query',platform=value['platform'],provider=value['provider'],method=value['method'],mode=value['data']['mode'],key=value['data']['service']['key'],types=len(value['data']['referencedTypes'])))
        for provider in host_inspect_providers(ctx):
            try:await provider['query']('wrong',{},NS(agent=agent,signal=signal))
            except Exception as error:rows.append(dict(stage='wrong-method',provider=provider['manifest']['id'],error=str(error)))
        try:ctx.cordisInspect.register(host_inspect_providers(ctx)[0])
        except Exception as error:rows.append(dict(stage='duplicate',error=str(error)))
        try:await ctx.cordisInspect.query('host','Config','listConfigs',{},agent,signal)
        except Exception as error:rows.append(dict(stage='config-no-loader',error=str(error)))
        await scopes[0].dispose()
        rows.append(dict(stage='first-scope-disposed',providers=[row['id'] for row in ctx.cordisInspect.list()],
            first=[row['name'] for row in ctx.tools.schemas(agents[0])],second=[row['name'] for row in ctx.tools.schemas(agents[1])]))
        await host.dispose()
        rows.append(dict(stage='host-disposed',providers=ctx.cordisInspect.list(),
            tools=[row['name'] for row in ctx.tools.schemas(agents[1])]))
    finally:
        for scope in scopes:await scope.dispose()
        await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_inspect_host.mts',scope='Actually mounted current Host providers and registry with two independent Agent tool scopes, exact provider query relay, scoped/dynamic schema visibility, duplicate rejection and reversible shared versus per-session ownership. Full client registry protocol and creative lifecycle are outside this part.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/extensions/inspect_providers_current.py',ROOT/'dsh/extensions/inspect_tools_current.py',ROOT/'dsh/extensions/inspect_api_current.py'])
