"""Pair scoped resource registry, prompt visibility and binary rendering."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.scope import create_scope,bind_scope_parent
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.mcp.resources_current import CurrentMcpResources,render_resource_result
    ctx=Context()
    for plugin in (CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentMcpResources):await ctx.plugin(plugin)
    owner,child,sibling=object(),object(),object();bind_scope_parent(child,owner)
    captured=[]
    class ScopeOwner(Plugin):
        inject=['mcpResources','tools']
        def apply(self,inner):captured.append(create_scope(inner,owner))
    await ctx.plugin(ScopeOwner)
    scoped=captured[0];rows=[]
    def provider(label):
        async def request(value,_):return dict(label=label,request=value,contents=[dict(blob='YWJj',uri='doc://a',text='text')],nested=dict(blob='\U0001f600'))
        return NS(request=request)
    async def snapshot(name):
        observations=[]
        for who,agent in [('global',None),('owner',owner),('child',child),('sibling',sibling)]:
            prompt=await ctx.systemPrompt.assemble({} if agent is None else dict(scope=agent))
            observations.append(dict(who=who,tools=sorted(ctx.tools.schemas(agent),key=lambda row:row['name']),
                prompt=[row['text'] for row in prompt['sections'] if row['name']=='mcp-resource-servers']))
        rows.append(dict(name=name,observations=observations))
    try:
        await snapshot('empty')
        first=ctx.mcpResources.register('docs',provider('global'));second=ctx.mcpResources.register('second',provider('second'))
        local=scoped.ctx.mcpResources.register('docs',provider('local'))
        await snapshot('global-and-local')
        try:scoped.ctx.mcpResources.register('docs',provider('duplicate'))
        except ValueError as error:rows.append(dict(name='duplicate',error=str(error)))
        for name,agent,server in [('global',None,'docs'),('owner',owner,'docs'),('child',child,'docs'),('sibling',sibling,'docs'),('missing',owner,'missing')]:
            try:
                value=await ctx.mcpResources._request(server,dict(method='resources/list',cursor=''),NS(agent=agent))
                rows.append(dict(name=name,value=value,content=render_resource_result(server,value)))
            except ValueError as error:rows.append(dict(name=name,error=str(error)))
        first();await snapshot('global-docs-removed')
        local();await snapshot('local-docs-removed')
        second();await snapshot('all-removed')
        await scoped.dispose()
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_resources.mts','Actual scoped resource services and tool registries: inherited/local/sibling visibility, prompt names, duplicate/unavailable diagnostics, independent provider lifetime, raw resource preservation and binary model projection.',[Path(__file__).resolve(),ROOT/'dsh/mcp/resources_current.py'])
