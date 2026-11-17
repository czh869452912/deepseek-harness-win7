import json
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.scope import create_scope
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.core.tools import CurrentToolsPlugin
from dsh.core.tool_executor_native import NativeToolExecutorPlugin
from dsh.extensions.cordis_manager_current import CurrentNativeCordisManager
from dsh.extensions.host_runner_current import CurrentDynamicCordisRunner
from dsh.extensions.inspect_providers_current import CurrentCordisInspectProviders
from dsh.extensions.inspect_tools_current import DEFINITIONS

NAMES={'cordis_define','cordis_run','cordis_stop','cordis_undefine','cordis_inspect_self','cordis_inspect_list','cordis_inspect_query'}


class Agent:
    def __init__(self,name):self.id=name


async def setup():
    ctx=Context()
    try:
        for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentDynamicCordisRunner,CurrentCordisInspectProviders]:await ctx.plugin(plugin)
        return ctx
    except BaseException:
        await ctx.fiber.dispose();raise


@pytest.mark.asyncio
async def test_current_host_with_two_native_creative_scopes(tmp_path):
    ctx=await setup();scopes=[];observations=[]
    try:
        for name in ['first','second']:
            agent=Agent(name);scope=create_scope(ctx,agent);agent.ctx=scope.ctx;scopes.append((agent,scope))
            await scope.ctx.plugin(CurrentNativeCordisManager)
            tools=ctx.tools.schemas(agent)
            assert {row['name'] for row in tools}==NAMES and len(tools)==7
            for definition in DEFINITIONS:
                tool=ctx.tools.get(definition['name'],agent)
                assert tool.description==definition['description']
                assert tool.parameters==definition['parameters']
            providers=ctx.cordisInspect.list()
            assert [row['id'] for row in providers]==['Service','Event','Config','Tool','Builtin']
            assert all(row['platform']=='host' for row in providers)
            observations.append(dict(scope=name,tools=tools,providers=providers))
        agent,scope=scopes[0]
        await scope.dispose()
        assert not ctx.tools.schemas(agent)
        assert [row['id'] for row in ctx.cordisInspect.list()]==['Service','Event','Config','Tool','Builtin']
        second,other=scopes[1]
        exec=NS(agent=second,signal=AbortController().signal)
        query=ctx.tools.get('cordis_inspect_query',second)
        value=await query.handler(dict(platform='host',provider='Tool',method='listTools',input={}),exec)
        assert {row['name'] for row in value['data']['tools']}==NAMES
        builtin=await query.handler(dict(platform='host',provider='Builtin',method='listBuiltins',input={}),exec)
        assert builtin['data']['builtins']
        await other.dispose()
        assert not ctx.tools.schemas(second)
        assert [row['id'] for row in ctx.cordisInspect.list()]==['Service','Event','Config','Tool']
        (tmp_path/'creative-scope-observations.json').write_text(json.dumps(observations),encoding='utf-8')
    finally:
        for _,scope in scopes:await scope.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_native_seven_tool_workflow_uses_real_current_runner(tmp_path):
    ctx=await setup();agent=Agent('owner');scope=create_scope(ctx,agent);agent.ctx=scope.ctx
    try:
        await scope.ctx.plugin(CurrentNativeCordisManager)
        execution=NS(agent=agent,signal=AbortController().signal)
        async def call(name,args):return await ctx.tools.get('cordis_'+name,agent).handler(args,execution)
        source="def plugin(ctx):\n    harness.handle('echo', lambda args: args)\n"
        defined=await call('define',dict(plugin=dict(kind='new',idPrefix='native'),name='Python fixture',purpose='Verify Native Creative composition',code=dict(host=source)))
        pid=defined['pluginId'];package=defined['packageId']
        started=await call('run',dict(pluginId=pid,packageId=package,mode='run'))
        assert started['status']=='running'
        echoed=await ctx.dynamicCordisRunner.invoke(pid,started['pluginRunId'],'echo',dict(message='hello'))
        assert echoed==dict(ok=True,value=dict(message='hello'))
        inspected=await call('inspect_self',dict(pluginId=pid,packageId=package))
        assert inspected['code']['host']==source
        assert inspected['runtime']['state']=='running'
        assert await call('stop',dict(pluginId=pid))==dict(pluginId=pid)
        assert await call('undefine',dict(pluginId=pid))==dict(pluginId=pid,wasRunning=False)
        assert not ctx.dynamicCordisRunner.inventory()
        (tmp_path/'creative-workflow-observations.json').write_text(json.dumps(dict(defined=defined,started=started,echoed=echoed,inspected=inspected)),encoding='utf-8')
    finally:await scope.dispose();await ctx.fiber.dispose()
