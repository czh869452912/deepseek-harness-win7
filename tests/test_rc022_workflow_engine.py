import asyncio
import os
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.workflow.ptc_engine import PtcWorkflowEngine
from scripts.rc022_workflow_engine_probe import observe

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Private VM parser targets Windows')


@pytest.mark.asyncio
async def test_current_engine_admission_and_lifecycle():
    rows=await observe()
    assert len(rows)==12 and all(row['events']==0 for row in rows[:-1])
    run=rows[-1]
    assert run['result']['value']==dict(value=[1])
    assert [event['event'] for event in run['events']]==['start','phase','end']
    assert 'value' not in run['events'][-1]['data'][0]
    assert run['initial'][0]['limits']['maxTotalAgents']==2


async def setup(start):
    ctx=Context();await ctx.plugin(JavaScriptRuntime)
    async def ensure(*_):return 'C:/engine'
    provider=NS(name='stub',capabilities=dict(outputSchema=True),inheritsParentContext=False)
    for name,value in [('subagents',NS(getProvider=lambda _:provider,startActivation=start)),('workingDirectory',NS(ensure=ensure)),('sandboxPolicy',NS(resolve=lambda _:dict(mode='read-only')))]:ctx.set_service(name,value)
    owner=await ctx.plugin(PtcWorkflowEngine,dict(provider='stub'))
    return ctx,owner


@pytest.mark.asyncio
async def test_engine_unload_preserves_held_run_and_children():
    entered=asyncio.Event();release=asyncio.Event();disposed=[]
    async def start(spec):
        entered.set();await release.wait()
        result=asyncio.get_event_loop().create_future();result.set_result(dict(output=[dict(type='text',text='held')],stopReason='completed'))
        async def dispose():disposed.append('child')
        return dict(childId='child',result=result,dispose=dispose)
    ctx,owner=await setup(start);events=[]
    ctx.on('workflow/end',lambda info,result:events.append(result))
    run=ctx.workflowEngine.start(dict(script="return await agent('task')",meta=dict(name='held',description='unload'),parent=NS(session=object())))
    try:
        await asyncio.wait_for(entered.wait(),5);await owner.dispose()
        assert ctx.get('workflowEngine') is None and not run.result.done()
        release.set();result=await asyncio.wait_for(asyncio.shield(run.result),5);await asyncio.sleep(0)
        assert result==dict(value='held',stopReason='completed',agentsStarted=1)
        assert events==[dict(stopReason='completed',agentsStarted=1)]
        assert disposed==['child'] and not ctx.jsRuntime._workers
    finally:release.set();await run.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_existing_workflow_and_ralph_tools_use_new_engine():
    from dsh.core.tools import ToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.workflow.tool_workflow import ToolWorkflowPlugin
    from dsh.workflow.tool_ralph import ToolRalphPlugin
    from test_ralph_and_workflow import Records, execute, COMPLETE
    calls=[];disposed=[]
    async def start(spec):
        calls.append(spec)
        result=asyncio.get_event_loop().create_future()
        result.set_result(dict(output=[],stopReason='completed',structured=COMPLETE))
        async def dispose():disposed.append(spec['label'])
        return dict(childId='child',result=result,dispose=dispose)
    ctx,owner=await setup(start)
    try:
        await ctx.plugin(ToolsPlugin);await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolWorkflowPlugin);await ctx.plugin(ToolRalphPlugin)
        parent=NS(id='parent',session=Records(),ctx=ctx,options={})
        output=await execute(ctx,parent,dict(script="log('tool'); return args",meta=dict(name='tool',description='consumer'),args=dict(answer=42)),name='workflow')
        assert not output.is_error and output.value['result']==dict(answer=42)
        output=await execute(ctx,parent,dict(objective='done',maxRounds=1),name='ralph')
        assert not output.is_error,output.content
        assert output.value['result']['status']=='complete' and output.value['agentsStarted']==1
        assert len(calls)==len(disposed)==1 and calls[0]['delivery']=='caller'
        assert [event['type'] for event in parent.session.events if event['type'].endswith('run-end')]==['tool-workflow/run-end']
        assert not ctx.jsRuntime._workers
    finally:await owner.dispose();await ctx.fiber.dispose()
