import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.cordis.volatile import WRITE
from dsh.shell.executor_current import CurrentPwshExecutor
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from scripts.rc022_shell_execution_probe import observe


@pytest.mark.asyncio
async def test_canonical_executor_lifecycle_and_original_error_projection(tmp_path,monkeypatch):
    import scripts.rc022_shell_execution_probe as probe
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await observe()}
    assert rows['normal']['sameResult'] is True
    assert rows['normal']['calls'][0]['env']==dict(NO_COLOR='0',PAGER='managed',GIT_PAGER='cat')
    assert rows['sync-failure']['initial']=='killed' and rows['sync-failure']['originalError']
    assert rows['async-failure']['originalError']
    assert rows['kill']['first'] is True and rows['kill']['second'] is False
    assert rows['timeout']['result']['timedOut'] and not rows['timeout']['result']['aborted']
    assert rows['abort']['result']['aborted'] and not rows['abort']['result']['timedOut']
    assert rows['none']['before']=='running'
    assert rows['prepare-timeout']['spawns']==0 and rows['prepare-timeout']['started']==0
    assert rows['prepare-timeout']['result']['timedOut'] and rows['prepare-abort']['originalError']


@pytest.mark.asyncio
async def test_live_volatile_budgets_validate_at_next_resolve_and_optional_defaults():
    ctx=Context();ctx.set_service('subprocess',NS());await ctx.plugin(CurrentPwshExecutor);shell=ctx.shell
    try:
        assert shell.pwshPath and shell.resolve(dict(command='test'))['onExpiry']=='kill'
        getattr(shell.entries['maxOutputBytes'],WRITE)(8)
        assert shell.resolve(dict(command='test'))['stdoutMaxBytes']==8
        getattr(shell.entries['timeoutMs'],WRITE)(0)
        with pytest.raises(ValueError,match='timeoutMs must be a positive finite'):shell.resolve(dict(command='test'))
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Actual canonical Windows Job process')
async def test_actual_powershell_utf8_spill_nonzero_exit_and_reload_ownership(tmp_path):
    ctx=Context();provider=await ctx.plugin(AuthorizedLocalSubprocessRuntime);executor=await ctx.plugin(CurrentPwshExecutor,dict(cwd=str(tmp_path),maxOutputBytes=8));shell=ctx.shell;runtime=ctx.subprocess
    try:
        process=await shell.execute(shell.resolve(dict(command="[Console]::Write(('汉' * 100)); exit 5",timeoutMs=10000)))
        result=await asyncio.wait_for(process.result(),15)
        assert result['exitCode']==5 and not result['timedOut'] and not result['aborted']
        assert result['stdout']['truncated'] and result['stdout']['text']==('汉'*100).encode('utf-8')[-8:].decode('utf-8',errors='replace')
        assert Path(result['stdout']['spillPath']).read_text(encoding='utf-8')=='汉'*100
        live=await shell.execute(shell.resolve(dict(command='Start-Sleep -Seconds 30',onExpiry='none',timeoutMs=1)))
        await executor.dispose();await asyncio.sleep(.02)
        assert live.status=='running' and runtime.live
        await provider.dispose();await asyncio.wait_for(live.done,5)
        assert not runtime.live and not runtime.ordinary_cleanups
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Actual canonical Windows Job process')
async def test_actual_powershell_deadline_and_failed_spawn_keep_distinct_results(tmp_path):
    ctx=Context();await ctx.plugin(AuthorizedLocalSubprocessRuntime);executor=await ctx.plugin(CurrentPwshExecutor,dict(cwd=str(tmp_path)));shell=ctx.shell
    try:
        process=await shell.execute(shell.resolve(dict(command='Start-Sleep -Seconds 30',timeoutMs=300)))
        result=await asyncio.wait_for(process.result(),5)
        assert result['timedOut'] and not result['aborted'] and result['exitCode']==1
        getattr(shell.entries['pwshPath'],WRITE)(str(tmp_path/'missing-pwsh.exe'))
        failed=await shell.execute(shell.resolve(dict(command='unused',timeoutMs=1000)));await failed.done
        assert failed.status=='killed' and failed.observed.stderr.readFrom(0)['text'].startswith('subprocess failed before reporting an outcome: ')
        with pytest.raises(FileNotFoundError):await failed.result()
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_execute_waiter_cancellation_preserves_preparation_and_published_process():
    ctx=Context();future=asyncio.get_running_loop().create_future();gate=asyncio.get_running_loop().create_future();empty=NS(readFrom=lambda _:dict(text='',lossy=False,nextOffset=0));calls=[]
    def spawn(spec):calls.append(spec);return NS(done=future,terminate=lambda:None,collected=dict(stdout=empty,stderr=empty))
    ctx.set_service('subprocess',NS(spawn=spawn));await ctx.plugin(CurrentPwshExecutor,dict(pwshPath='fake'));shell=ctx.shell
    async def prepare(signal):await gate;return ['fake']
    operation=shell.execute_argv(shell.resolve(dict(command='test',onExpiry='none')),prepare)
    async def wait():return await operation
    task=asyncio.create_task(wait());await asyncio.sleep(0);task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):await task
        assert not gate.cancelled();gate.set_result(None);process=await operation
        result=process.result();other=asyncio.ensure_future(result);await asyncio.sleep(0);other.cancel()
        with pytest.raises(asyncio.CancelledError):await other
        future.set_result(dict(exitCode=0,signal=None));assert (await process.result())['exitCode']==0
        assert len(calls)==1
    finally:
        if not gate.done():gate.set_result(None)
        if not future.done():future.set_result(dict(exitCode=0,signal=None))
        await ctx.fiber.dispose()
