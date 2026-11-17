import json
from types import SimpleNamespace

import pytest

from dsh.cordis import Context, Loader, Schema
from dsh.core.abort import AbortController
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.core.tools import CurrentToolsPlugin
from dsh.core.tool_executor_native import NativeToolExecutorPlugin
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.extensions.inspect_registry_current import CurrentCordisInspectRegistryService
from dsh.extensions.inspect_providers_current import CurrentCordisInspectProviders
from dsh.extensions.inspect_tools_current import CurrentCordisInspectTools
from scripts.rc022_inspect_api_probe import observe as api_observe
from scripts.rc022_inspect_host_probe import observe as host_observe


@pytest.mark.asyncio
async def test_complete_current_catalog_contracts(tmp_path):
    rows=await api_observe()
    (tmp_path/'inspect-api-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==207
    assert rows[-1]['kind']=='manifests'
    assert [row['id'] for row in rows[-1]['value']]==['Service','Event','Config','Tool']
    assert any(row.get('key')=='tools' and row.get('bytes',0)>1000 for row in rows)
    assert any(row.get('error')=='no catalogued Service named "unknown"' for row in rows)
    assert any(row.get('error')=='no catalogued Event named "cordis/query"' for row in rows)


@pytest.mark.asyncio
async def test_actual_shared_host_and_independent_agent_tools(tmp_path):
    rows=await host_observe()
    (tmp_path/'inspect-host-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==12
    first,second=[row for row in rows if row['stage']=='tool-view']
    assert 'private_fixture' in first['tools'] and 'private_fixture' not in second['tools']
    assert first['tools'].count('cordis_inspect_query')==second['tools'].count('cordis_inspect_query')==1
    disposed=next(row for row in rows if row['stage']=='first-scope-disposed')
    assert disposed['providers']==['Service','Event','Config','Tool']
    assert disposed['first']==['global_fixture']
    assert 'cordis_inspect_query' in disposed['second']
    assert rows[-1]['providers']==[] and 'cordis_inspect_query' in rows[-1]['tools']


@pytest.mark.asyncio
async def test_current_inspect_tool_reaches_actual_live_loader_config(tmp_path):
    ctx=Context();ctx.baseUrl=tmp_path.as_uri()+'/'
    try:
        for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,
            CurrentCordisInspectRegistryService,JavaScriptRuntime,Loader,CurrentCordisInspectProviders,CurrentCordisInspectTools]:
            await ctx.plugin(plugin)
        def sample(owner,config):pass
        sample.Config=Schema.object({'enabled':Schema.boolean().default(True)})
        ctx.loader.register_plugin_class('sample',sample)
        await ctx.loader.create(dict(id='sample',name='sample'))
        tool=ctx.tools.get('cordis_inspect_query')
        value=await tool.handler(dict(platform='host',provider='Config',method='listConfigs',input=dict(entry='sample')),
            SimpleNamespace(agent=SimpleNamespace(id='agent'),signal=AbortController().signal))
        assert value['data']['status']=='schema'
        assert value['data']['schema']['anyOf'][0]['properties']['enabled']['default'] is True
        assert not ctx.jsRuntime._workers
        (tmp_path/'inspect-tool-config-observations.json').write_text(json.dumps(value),encoding='utf-8')
    finally:await ctx.fiber.dispose()
