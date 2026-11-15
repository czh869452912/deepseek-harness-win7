import asyncio
import shutil

import pytest

from dsh.cordis import Context
from dsh.javascript.runtime import JavaScriptRuntime,JavaScriptRuntimeError
from dsh.terminal.screen_runtime import TerminalScreenRuntime


@pytest.mark.asyncio
async def test_actual_pinned_xterm_on_win7_engine_markers_reflow_trim_and_ansi():
    from scripts.rc022_terminal_engine_probe import observe
    rows=await observe()
    assert rows[-1] == dict(name='disposed',engines=0,workers=0)
    trimmed=next(row for row in rows if row.get('case')==3 and row.get('step')==2)
    assert trimmed['marks']['old']['truncated']
    alternate=next(row for row in rows if row.get('case')==1 and row.get('step')==2)
    assert alternate['page']['text']=='full screen app' and alternate['marks']['normal']['truncated'] is False
    assert any('\x1b[' in row.get('snapshot','') for row in rows)


@pytest.mark.asyncio
async def test_mark_operations_order_with_following_write_and_disposal_releases_worker():
    ctx=Context()
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
        screen=await ctx.terminalScreens.open(dict(cols=10,rows=4,scrollback=4));worker=screen.worker
        await screen.write('old\r\n$ ');mark=screen.mark()
        await screen.write('new\r\nend')
        assert mark.lines()==dict(lines=['$ new','end'],truncated=False)
        mark.dispose();await screen.drain()
        assert mark.lines()==dict(lines=['old','$ new','end'],truncated=True)
        await screen.dispose()
        assert worker.process.returncode is not None and worker.closed.done()
        assert not ctx.terminalScreens.engines and not ctx.jsRuntime._workers
        with pytest.raises(RuntimeError,match='screen was closed'):mark.lines()
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_screen_creation_waits_for_and_releases_its_owned_worker():
    ctx=Context();entered=asyncio.Event();release=asyncio.Event();task=None;worker=[]
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime);original=ctx.jsRuntime.open
        async def held(*args,**kwargs):
            result=await original(*args,**kwargs);worker.append(result);entered.set();await release.wait();return result
        ctx.jsRuntime.open=held
        task=asyncio.ensure_future(ctx.terminalScreens.open(dict(cols=10,rows=4,scrollback=4)))
        await asyncio.wait_for(entered.wait(),2);task.cancel();release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert worker[0].process.returncode is not None
        assert not ctx.terminalScreens.engines and not ctx.terminalScreens.creating and not ctx.jsRuntime._workers
    finally:
        release.set()
        if task is not None:await asyncio.gather(task,return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_provider_unload_joins_late_creation_and_rejects_further_opens():
    ctx=Context();entered=asyncio.Event();release=asyncio.Event();opening=unload=None;workers=[]
    try:
        await ctx.plugin(JavaScriptRuntime);fork=await ctx.plugin(TerminalScreenRuntime);owner=ctx.terminalScreens;original=ctx.jsRuntime.open
        async def held(*args,**kwargs):
            worker=await original(*args,**kwargs);workers.append(worker);entered.set();await release.wait();return worker
        ctx.jsRuntime.open=held;opening=asyncio.ensure_future(owner.open(dict(cols=10,rows=4,scrollback=4)))
        await asyncio.wait_for(entered.wait(),2);unload=asyncio.ensure_future(fork.dispose());await asyncio.sleep(0);release.set()
        with pytest.raises(RuntimeError,match='disposed during creation'):await opening
        await unload
        assert all(worker.process.returncode is not None for worker in workers) and not owner.engines and not owner.creating
        with pytest.raises(RuntimeError,match='runtime disposed'):await owner.open(dict(cols=10,rows=4,scrollback=4))
    finally:
        release.set();await asyncio.gather(*(task for task in (opening,unload) if task is not None),return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_worker_crash_surfaces_to_consumer_and_cleanup_removes_owner_record():
    ctx=Context()
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
        screen=await ctx.terminalScreens.open(dict(cols=10,rows=4,scrollback=4));screen.worker.process.kill();await screen.worker.closed
        with pytest.raises(JavaScriptRuntimeError):await screen.snapshot()
        with pytest.raises(JavaScriptRuntimeError):await screen.dispose()
        assert not ctx.terminalScreens.engines and not ctx.jsRuntime._workers
    finally:await ctx.fiber.dispose()


def test_tampered_headless_resource_is_refused_before_worker_spawn(tmp_path,monkeypatch):
    from dsh.terminal import screen_runtime
    resources=tmp_path/'resources';shutil.copytree(str(screen_runtime.RESOURCE_ROOT),str(resources))
    (resources/'headless.js').write_text('tampered',encoding='utf-8');monkeypatch.setattr(screen_runtime,'RESOURCE_ROOT',resources)
    with pytest.raises(RuntimeError,match='resource differs: headless.js'):screen_runtime.resources()
