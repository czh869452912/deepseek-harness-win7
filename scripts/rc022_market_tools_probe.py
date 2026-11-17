"""Read-only market tool with controlled index service and actual tool dispatch."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
DATA=None


def fixture():
    versions=[dict(version=str(index),publishTimestamp=stamp,compatibility=dict(compatible=index%2==0),install=dict(spec='bundle@'+str(index),**(dict(registry='https://registry.invalid/') if index%2==0 else {}))) for index,stamp in enumerate([0,1790476800,-0.001,-62167219200,253402300800,8640000000000,-8640000000000])]
    entries=[dict(name='bundle',title=dict(en='E'*299+'😀',zh='标题'),description=dict(zh='本地描述'),author='A'*301,homepage='https://example.invalid/',repository=dict(url='git'),metadata=dict(category='tools',labels=['official'],sortKeys=dict(downloads=5)),installation=dict(status='not-installed'),defaultVersion='0',versions=versions),dict(name='missing-default',title=dict(zh='本地'),metadata=dict(labels=[],sortKeys={}),installation=dict(status='installed'),defaultVersion='absent',versions=versions[:1])]
    cases=[dict(action='list_indexes')]
    for query in [None,'',' ','\ufeff','中文']:
        cases.append(dict(action='list_plugins',target='market',**({} if query is None else dict(query=query)),offset=0,limit=2))
    for offset,limit in [(0,2),(2,3),(5,100),(7,2),(50,1)]:cases.append(dict(action='list_versions',target='market',name='bundle',offset=offset,limit=limit))
    cases.extend([dict(action='list_plugins'),dict(action='list_versions',target='market'),dict(action='list_versions',target='market',name='missing')])
    for key in ['offset','limit']:
        for value in [-1,0,1.5,101,None]:cases.append(dict(dict(action='list_plugins',target='market'),**{key:value}))
    return dict(versions=versions,entries=entries,cases=cases)


async def observe():
    from dsh.cordis import Context
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin,ToolExecutionInput
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.core.abort import NEVER_ABORTED
    from dsh.boot.plugin_market_tools import CurrentPluginMarketTools,DESCRIPTOR
    ctx=Context();requests=[];data=fixture();rows=[]
    async def search(target,request):requests.append([target,request]);return dict(title=dict(en='Market'),entries=data['entries'],total=2,nextOffset=None)
    async def entry(target,name):return data['entries'][0] if name=='bundle' else None
    market=SimpleNamespace(listIndexes=lambda:[dict(url='market'),dict(url='offline',title=dict(en='Market',zh='市场'),error='offline')],search=search,entry=entry)
    class Provider:
        @staticmethod
        def apply(ctx):ctx.provide('pluginMarket',market)
    try:
        for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin]:await ctx.plugin(plugin)
        fiber=await ctx.plugin(CurrentPluginMarketTools);rows.append(dict(name='absent',visible=ctx.tools.get('plugin_market') is not None))
        provider=await ctx.plugin(Provider);rows.append(dict(name='descriptor',value=DESCRIPTOR))
        for index,args in enumerate(data['cases']):
            before=len(requests);result=await ctx.tools.execute(ToolExecutionInput('market-'+str(index),'plugin_market',args,signal=NEVER_ABORTED))
            rows.append(dict(name=str(index),value=dict(isError=result.is_error,value=result.value,content=result.content),requests=requests[before:],presentation=ctx.tools.get('plugin_market').present_call(args)))
        await provider.dispose();rows.append(dict(name='withdrawn',visible=ctx.tools.get('plugin_market') is not None));await fiber.dispose();return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(fixture()),encoding='utf-8');return [path]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_market_tools.mts','Actual optional tool activation/withdrawal and dispatch: exact descriptor/presentation, all listing selectors, declared paging bounds, English fallback/UTF-16 truncation, withheld untranslated fields, chosen version and full Date range, errors and query sort. Market index service controlled; its network/cache/parser is not certified.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_market_tools.py',ROOT/'dsh/boot/plugin_market_tools.json',ROOT/'scripts/oracles/rc022_market_definition.mts'],prepare=prepare)
