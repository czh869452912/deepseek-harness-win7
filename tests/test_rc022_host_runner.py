import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.cordis.utils import Symbols
from dsh.core.abort import AbortController
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.core.tools import CurrentToolsPlugin
from dsh.core.tool_executor_native import NativeToolExecutorPlugin
from dsh.extensions.host_runner_current import CurrentDynamicCordisRunner
from dsh.extensions.inspect_registry_current import CurrentCordisInspectRegistryService
from scripts.rc022_host_runner_probe import observe
from scripts.rc022_inspect_registry_probe import Clock, manifest


@pytest.mark.asyncio
async def test_current_runner_config_and_actual_journeys(tmp_path):
    rows=await observe()
    (tmp_path/'host-runner-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==28
    journeys={row['stage']:row for row in rows if row['stage']!='config'}
    assert journeys['failure']['results'][-2]['status']=='starting'
    assert len(journeys['guard']['messages'])==len(journeys['render']['messages'])==2
    assert len(journeys['handler']['messages'])==3
    assert [row['message'] for row in journeys['handler']['results'][-4:]]==['handler failed','handler failed','c','b\0c']
    assert len(journeys['panel']['injected'])==2
    assert not journeys['foreign-agent']['injected']
    for row in journeys.values():
        assert row['timeout']==37
        for message in row['messages']+row['injected']:
            assert message['source']==dict(kind='cordis-host-runner')
            assert 'activate it autonomously' not in message['content'][0]['text']


async def mounted():
    ctx=Context()
    try:
        for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin]:await ctx.plugin(plugin)
        fiber=ctx.plugin(CurrentDynamicCordisRunner,dict(clientInspectTimeoutMs=37));await fiber
        return ctx,fiber,ctx.get('dynamicCordisRunner')
    except BaseException:
        await ctx.fiber.dispose();raise


@pytest.mark.asyncio
async def test_current_runner_owns_inspect_deadline_and_disposal(monkeypatch):
    ctx,fiber,runner=await mounted();registry=ctx.get('cordisInspect')
    try:
        assert getattr(registry,Symbols.original) is runner.inspect_registry
        assert isinstance(runner.inspect_registry,CurrentCordisInspectRegistryService)
        registry.syncClientManifest([manifest()]);clock=Clock();signal=AbortController().signal
        monkeypatch.setattr(asyncio.get_running_loop(),'call_later',clock.later)
        task=asyncio.create_task(registry.query('client','Service','listService',{},NS(id='agent'),signal))
        assert next(iter(clock.pending.values()))[2]==0.037
        await fiber.dispose()
        with pytest.raises(RuntimeError,match='Client inspect registry was disposed'):await task
        assert not registry._pending and not clock.pending and not signal._listeners
        assert runner._spare.closed and not runner._host_processes
        assert ctx.get('cordisInspect') is None and ctx.get('dynamicCordisRunner') is None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_invalid_config_has_no_runner_or_host_process():
    ctx=Context()
    try:
        for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin]:await ctx.plugin(plugin)
        fiber=ctx.plugin(CurrentDynamicCordisRunner,dict(clientInspectTimeoutMs=1.5))
        with pytest.raises(Exception,match='multiple of'):await fiber
        assert ctx.get('dynamicCordisRunner') is None and ctx.get('cordisInspect') is None
        await fiber.dispose()
    finally:await ctx.fiber.dispose()
