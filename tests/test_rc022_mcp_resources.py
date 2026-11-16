import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.core.scope import create_scope
from dsh.core.tools import ToolExecutionInput
from scripts.rc022_candidate_fixture import setup


NAMES={'list_mcp_resources','list_mcp_resource_templates','read_mcp_resource'}


@pytest.mark.asyncio
async def test_actual_loader_resource_tools_scope_cursors_raw_binary_and_provider_lifetime(tmp_path):
    ctx=await setup(tmp_path,extra=[('mcp-resources',{})]);lease=None;other=None;calls=[]
    async def request(value,execution):
        calls.append(dict(request=value,agent=execution.agent.id))
        return dict(contents=[dict(uri='doc://a',blob='YWJj',text='readable')],nextCursor='next')
    class Provider(Plugin):
        inject=['mcpResources','tools']
        def apply(self,inner):
            create_scope(inner,lease.agent).ctx.mcpResources.register(self.config['server'],NS(request=request))
    try:
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='m')))
        other=await ctx.agents.create(dict(sessionId='other',agentOptions=dict(provider='script',model='m')))
        first=await ctx.plugin(Provider,config=dict(server='first'))
        second=await ctx.plugin(Provider,config=dict(server='second'))
        def visible(agent):return NAMES.intersection(row['name'] for row in ctx.tools.schemas(agent))
        assert visible(lease.agent)==NAMES and not visible(other.agent) and not visible(None)
        results=[]
        for name,args in [('list_mcp_resources',dict(server='second',cursor='')),
            ('list_mcp_resource_templates',dict(server='second',cursor='next')),
            ('read_mcp_resource',dict(server='second',uri='doc://a'))]:
            result=await ctx.tools.execute(ToolExecutionInput(name,name,args,agent=lease.agent,signal=NEVER_ABORTED))
            assert not result.is_error,result.error
            assert result.value['contents'][0]['blob']=='YWJj'
            assert 'YWJj' not in json.dumps(result.content) and '4 base64 characters' in json.dumps(result.content)
            results.append(dict(value=result.value,content=result.content))
        assert [row['request'] for row in calls]==[dict(method='resources/list',cursor=''),dict(method='resources/templates/list',cursor='next'),dict(method='resources/read',uri='doc://a')]
        await first.dispose()
        assert visible(lease.agent)==NAMES
        result=await ctx.tools.execute(ToolExecutionInput('still','list_mcp_resources',dict(server='second'),agent=lease.agent,signal=NEVER_ABORTED))
        assert not result.is_error,result.error
        await second.dispose()
        assert not visible(lease.agent)
        (tmp_path/'mcp-resource-observations.json').write_text(json.dumps(dict(calls=calls,results=results,independentLifetime=True),indent=2),encoding='utf-8')
    finally:
        if lease is not None:await lease.dispose()
        if other is not None:await other.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_scoped_resource_unload_joins_tool_cleanup_and_parallel_requests_are_independent(tmp_path,monkeypatch):
    from dsh.mcp import resources_current as module
    ctx=await setup(tmp_path,extra=[('mcp-resources',{})]);lease=None
    gate=asyncio.Event();started=asyncio.Event();request_gate=asyncio.Event();request_started=asyncio.Event()
    real_scope=module.create_scope
    def tracked_scope(*args):
        scope=real_scope(*args)
        async def cleanup():started.set();await gate.wait()
        scope.ctx.effect(lambda:cleanup)
        return scope
    monkeypatch.setattr(module,'create_scope',tracked_scope)
    async def request(value,execution):
        if value.get('cursor')=='hold':request_started.set();await request_gate.wait()
        return dict(resources=[],cursor=value.get('cursor'))
    class Provider(Plugin):
        inject=['mcpResources','tools']
        def apply(self,inner):create_scope(inner,lease.agent).ctx.mcpResources.register('docs',NS(request=request))
    running=None;unload=None
    try:
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='m')))
        provider=await ctx.plugin(Provider)
        async def call(cursor):return await ctx.tools.execute(ToolExecutionInput(cursor,'list_mcp_resources',dict(server='docs',cursor=cursor),agent=lease.agent,signal=NEVER_ABORTED))
        running=asyncio.create_task(call('hold'));await asyncio.wait_for(request_started.wait(),3)
        second=await asyncio.wait_for(call('independent'),3)
        assert not second.is_error and not running.done()
        request_gate.set();assert not (await running).is_error
        unload=asyncio.ensure_future(provider.dispose());await asyncio.wait_for(started.wait(),3)
        for _ in range(5):await asyncio.sleep(0)
        assert not unload.done()
        assert not NAMES.intersection(row['name'] for row in ctx.tools.schemas(lease.agent))
        gate.set();await asyncio.wait_for(unload,3)
    finally:
        gate.set();request_gate.set()
        for task in (running,unload):
            if task is not None:await asyncio.gather(task,return_exceptions=True)
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()
