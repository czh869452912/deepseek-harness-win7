import asyncio
import os
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.subagent.runtime import SubagentRuntime
from dsh.workflow.tool_ralph import ToolRalphPlugin
from dsh.workflow.tool_workflow import ToolWorkflowPlugin
from dsh.workflow.workflow_service import WorkflowEngine, WorkflowError
from test_ralph_and_workflow import Provider, Records, execute, META, COMPLETE, CONTINUE, BLOCKED


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')


async def setup(provider=None, config=None):
    ctx = Context()
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(JavaScriptRuntime)
    await ctx.plugin(SubagentRuntime)
    provider = provider or Provider()
    ctx.get('subagents').registerProvider(provider)
    engine = await ctx.plugin(WorkflowEngine, config or {})
    await ctx.plugin(ToolRalphPlugin)
    await ctx.plugin(ToolWorkflowPlugin)
    parent = SimpleNamespace(id='parent', ctx=ctx, options={}, session=Records())
    return ctx, provider, parent, engine


@pytest.mark.asyncio
@pytest.mark.parametrize('reports,status', [([COMPLETE], 'complete'), ([BLOCKED], 'blocked'),
    ([CONTINUE, COMPLETE], 'complete'), ([CONTINUE, CONTINUE], 'budget-limited')])
async def test_original_ralph_script_executes_without_native_translation(reports, status):
    ctx, provider, parent, _ = await setup(Provider(reports))
    runtime = ctx.get('jsRuntime')
    try:
        assert not ctx.get('workflowEngine')._native_programs
        result = await execute(ctx, parent, dict(objective='Finish migration', maxRounds=len(reports)))
        assert not result.is_error, result.content
        assert result.value['result']['status'] == status
        assert result.value['result']['roundsStarted'] == len(reports)
        assert result.value['agentsStarted'] == len(reports)
        assert len(provider.requests) == len(reports)
        assert all(request['parent'] is parent and 'outputSchema' in request for request in provider.requests)
        assert all(child.disposed == 1 for child in provider.children)
        assert not runtime._workers
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_workflow_tool_executes_caller_functions_and_records_real_children():
    ctx, provider, parent, _ = await setup()
    try:
        result = await execute(ctx, parent, dict(meta=META, args=dict(prefix='任务'), script=
            'const prefix=args.prefix;const values=await pipeline([1,2],value=>agent(prefix+value));return {values,count:values.length}'), 'workflow')
        assert not result.is_error, result.content
        assert result.value['result'] == dict(values=['child answer', 'child answer'], count=2)
        assert result.value['agentsStarted'] == 2
        assert [request['prompt'][0]['text'] for request in provider.requests] == ['任务1', '任务2']
        assert [event['type'] for event in parent.session.events].count('tool-workflow/agent-start') == 2
        assert [event['type'] for event in parent.session.events].count('tool-workflow/agent-end') == 2
        assert not ctx.get('jsRuntime')._workers
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_held_javascript_run_starts_and_disposes_children_after_engine_unload():
    ctx, provider, parent, engine = await setup(Provider(pending=True))
    runtime = ctx.get('jsRuntime')
    run = ctx.get('workflowEngine').start(dict(meta=META, parent=parent,
        script='const first=await agent("first");return [first,await agent("second")]'))
    try:
        await asyncio.wait_for(provider.entered.wait(), 5)
        await engine.dispose()
        assert ctx.get('workflowEngine') is None
        assert ctx.get('jsRuntime') is not None
        provider.entered.clear()
        provider.children[0].result.set_result(dict(output=[dict(type='text', text='first')], stopReason='completed'))
        await asyncio.wait_for(provider.entered.wait(), 5)
        provider.children[1].result.set_result(dict(output=[dict(type='text', text='second')], stopReason='completed'))
        assert await asyncio.wait_for(asyncio.shield(run.result), 5) == dict(
            value=['first', 'second'], stopReason='completed', agentsStarted=2)
        await asyncio.wait_for(run.dispose(), 5)
        assert all(child.disposed == 1 for child in provider.children)
        assert not runtime._workers
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_late_provider_is_refused_before_slow_disposal_finishes():
    disposing, release_disposal, refused = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class SlowProvider(Provider):
        async def start(self, request):
            child = await super().start(request)
            original = child.dispose
            async def dispose():
                disposing.set()
                await release_disposal.wait()
                await original()
            child.dispose = dispose
            return child
    provider = SlowProvider()
    provider.release = asyncio.Event()
    ctx, _, parent, _ = await setup(provider)
    ctx.on('workflow/log', lambda info, message: refused.set() if message == 'refused' else None)
    run = ctx.get('workflowEngine').start(dict(meta=META, parent=parent,
        script='void agent("late").catch(()=>log("refused"));return "done"'))
    try:
        await asyncio.wait_for(provider.entered.wait(), 5)
        assert await asyncio.wait_for(asyncio.shield(run.result), 5) == dict(
            value='done', stopReason='completed', agentsStarted=1)
        assert provider.requests[0]['signal'].aborted
        disposal = run.dispose()
        assert disposal is run.dispose()
        provider.release.set()
        await asyncio.wait_for(disposing.wait(), 5)
        await asyncio.wait_for(refused.wait(), 5)
        assert not disposal.done()
        assert provider.children[0].disposed == 0
        release_disposal.set()
        await asyncio.wait_for(disposal, 5)
        assert provider.children[0].disposed == 1
        assert not run._children and not run._starts
        assert run._worker.closed.done()
    finally:
        provider.release.set()
        release_disposal.set()
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('script', ['await new Promise(()=>{})', 'await Promise.resolve();for(;;){}'])
async def test_cancellation_grace_physically_terminates_unsettled_script(script):
    ctx, _, parent, _ = await setup(config=dict(disposeGraceMs=30))
    run = ctx.get('workflowEngine').start(dict(meta=META, parent=parent, script=script))
    try:
        await asyncio.wait_for(asyncio.shield(run._opening), 5)
        run.cancel('')
        run.cancel('later reason')
        assert await asyncio.wait_for(asyncio.shield(run.result), 5) == dict(value=None, stopReason='cancelled',
            error='workflow run cancelled: ', agentsStarted=0)
        await asyncio.wait_for(run.dispose(), 5)
        assert run._worker.process.returncode is not None
        assert not ctx.get('jsRuntime')._workers
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('script', ['return {', 'export const meta = {};return 1'])
async def test_script_parse_fails_before_publication(script):
    ctx, provider, parent, _ = await setup()
    starts = []
    ctx.on('workflow/start', starts.append)
    try:
        with pytest.raises(WorkflowError) as caught:
            ctx.get('workflowEngine').start(dict(meta=META, parent=parent, script=script))
        assert caught.value.code == 'SCRIPT_PARSE'
        assert not starts and not provider.requests and not ctx.get('jsRuntime')._workers
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_missing_args_remain_javascript_undefined():
    ctx, _, parent, _ = await setup()
    run = ctx.get('workflowEngine').start(dict(meta=META, parent=parent, script='return args===undefined'))
    try:
        assert await asyncio.wait_for(asyncio.shield(run.result), 5) == dict(
            value=True, stopReason='completed', agentsStarted=0)
    finally:
        await run.dispose()
        await ctx.fiber.dispose()
