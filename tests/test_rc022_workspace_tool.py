import asyncio
import json
import os

import pytest

from dsh.cordis import Context
from dsh.core.cleanup import CleanupPromise
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.core.tools import CurrentToolsPlugin
from dsh.host import workspace_dependencies_current as module
from scripts.rc022_workspace_tool_probe import observe,cases


@pytest.mark.asyncio
async def test_mounted_tool_schema_output_retry_and_unregistration(tmp_path):
    rows=await observe(tmp_path/'files')
    (tmp_path/'workspace-tool-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==21
    assert all(row['stage']=='done' and row['removed'] and row['sameValue'] for row in rows[:4])
    assert rows[2]['firstFailed'] and rows[3]['cachedAfterRemoval']
    assert all(row['stage'] in ['schema','mount'] and 'error' in row for row in rows[4:])


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[False,True])
async def test_disposal_waits_for_shared_preparation_even_when_waiter_cancelled(monkeypatch,tmp_path,failure):
    calls=[];entered=asyncio.Event();release=asyncio.Event()
    async def work():
        entered.set();await release.wait()
        if failure:raise OSError('fixture failure')
        return dict(python='python',pythonPackages='packages',pythonDistributions={})
    def resolve(source):calls.append(source);return CleanupPromise(work())
    monkeypatch.setattr(module,'resolvePrimaryRuntime',resolve)
    ctx=Context();await ctx.plugin(CurrentSystemPrompt);await ctx.plugin(CurrentToolsPlugin)
    fiber=await ctx.plugin(module.CurrentWorkspaceDependencies,dict(source=str(tmp_path)))
    tool=ctx.tools.get('load_workspace_dependencies');one=tool.handler({});two=tool.handler({})
    assert one is two
    async def wait():return await one
    waiter=asyncio.create_task(wait());await entered.wait();waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    disposing=asyncio.ensure_future(fiber.dispose());await asyncio.sleep(0)
    assert not disposing.done() and calls==[str(tmp_path)]
    release.set();await disposing
    if failure:
        with pytest.raises(OSError,match='fixture failure'):await two
    else:assert (await two)['python']=='python'
    assert ctx.tools.get('load_workspace_dependencies') is None
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_registry_tool_pipeline_failure_retry_and_typed_render(tmp_path):
    from dsh.boot.plugin_registry import HARNESS_PLUGIN_CLASSES
    from dsh.core.abort import AbortController
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.core.tools import ToolExecutionInput
    from scripts.rc022_workspace_tool_probe import payload
    assert HARNESS_PLUGIN_CLASSES['@deepseek-ai/dsh-tool-workspace-dependencies']=='dsh.host.workspace_dependencies_current:CurrentWorkspaceDependencies'
    source=tmp_path/'source';raw=payload(source);(source/'runtime.json').unlink();environment=dict(os.environ)
    ctx=Context()
    try:
        await ctx.plugin(CurrentSystemPrompt);await ctx.plugin(CurrentToolsPlugin);await ctx.plugin(NativeToolExecutorPlugin)
        await ctx.plugin(module.CurrentWorkspaceDependencies,dict(source=str(source),root=str(tmp_path/'installed')))
        async def call(identity):
            return await ctx.tools.execute(ToolExecutionInput(identity,'load_workspace_dependencies',{},signal=AbortController().signal))
        first=await call('missing');assert first.isError
        (source/'runtime.json').write_text(raw,encoding='utf-8')
        second=await call('retry');assert not second.isError
        assert json.loads(second.content[0]['text'])==second.value
        assert second.value['pythonDistributions']=={'Pillow':'10.4.0'} and 'node' not in second.value
        assert dict(os.environ)==environment
    finally:await ctx.fiber.dispose()
