import asyncio
import ctypes
import os
import sys

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime

pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='actual Win7 WinPTY C ABI')


def spec(tmp_path,**changes):
    value=dict(argv=[os.path.join(os.environ['SystemRoot'],'System32','cmd.exe'),'/q'],cwd=str(tmp_path),
        cols=80,rows=24,graceMs=1000,terminalType='xterm-256color',shellActivity=True,
        env=dict(DSH_SESSION_ID='native-terminal-test'),signal=AbortController().signal)
    value.update(changes);return value


async def until(predicate):
    async def wait():
        while not predicate():await asyncio.sleep(.01)
    await asyncio.wait_for(wait(),6)


@pytest.mark.asyncio
async def test_actual_canonical_winpty_resize_environment_unicode_final_output_and_retained_exit(tmp_path):
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx);handle=None;reader=None;chunks=[]
    try:
        handle=await runtime.spawnTerminal(spec(tmp_path))
        async def read():
            async for chunk in handle.output:chunks.append(chunk)
        reader=asyncio.ensure_future(read())
        text=lambda:b''.join(chunks).decode('utf-8','replace')
        await handle.write('@echo off\r');await handle.write('echo TERM=[%TERM%] SESSION=[%DSH_SESSION_ID%]\r')
        await until(lambda:'TERM=[xterm-256color] SESSION=[native-terminal-test]' in text())
        await handle.resize(73,11)
        await handle.write('powershell.exe -NoProfile -Command "\'SIZE=\' + $Host.UI.RawUI.WindowSize.Width + \'x\' + $Host.UI.RawUI.WindowSize.Height"\r')
        await until(lambda:'SIZE=73x11' in text())
        await handle.write('echo 中文控制台\r');await until(lambda:'中文控制台' in text())
        assert await handle.inspectForeground()==dict(processGroupId=handle.pid,inputWaiting=False)
        assert (await handle.inspectActivity())['state']=='unknown'
        await handle.write('echo FINAL-TAIL & exit /b 7\r')
        assert (await asyncio.wait_for(asyncio.shield(handle.done),5))==dict(exitCode=7,signal=None)
        await asyncio.wait_for(reader,5);assert 'FINAL-TAIL' in text()
        assert handle in runtime.terminals
        await handle.terminate()
        assert not runtime.terminals and handle.raw.process is None and handle.raw.job is None and handle.raw.pty is None
        assert handle.raw.output is None and handle.reader.done() and handle.pipe.closed
        assert (await handle.inspectActivity())['state']=='idle'
        with pytest.raises(RuntimeError,match='exited'):await handle.resize(80,24)
    finally:
        if handle is not None:await handle.terminate()
        if reader is not None:await asyncio.gather(reader,return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_owned_job_activity_busy_and_teardown_closes_descendant_and_unconsumed_output(tmp_path):
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx);handle=None;child=None
    try:
        handle=await runtime.spawnTerminal(spec(tmp_path));pidfile=tmp_path/'child.pid'
        await handle.write('@echo off\r')
        code="import os,time,signal;signal.signal(signal.SIGINT,lambda *args:open('interrupt.txt','w',encoding='utf-8').write('yes'));open('child.pid','w',encoding='utf-8').write(str(os.getpid()));time.sleep(30)"
        await handle.write('"'+sys.executable+'" -c "'+code+'"\r')
        await until(lambda:pidfile.exists() and pidfile.read_text(encoding='utf-8'))
        kernel=handle.raw.api.kernel;kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
        child=handle.raw.api.check(kernel.OpenProcess(0x100000,False,int(pidfile.read_text(encoding='utf-8'))),'OpenProcess owned test child')
        first=await handle.inspectActivity();second=await handle.inspectActivity()
        assert first['state']=='busy' and second==first
        with pytest.raises(RuntimeError,match='refusing to SIGKILL'):await handle.signalForeground('SIGKILL')
        for name in ('SIGHUP','SIGTSTP'):
            with pytest.raises(RuntimeError,match='unsupported on Windows'):await handle.signalForeground(name)
        assert await handle.signalForeground('SIGINT')==handle.pid
        await until(lambda:(tmp_path/'interrupt.txt').exists())
        await asyncio.wait_for(handle.terminate(),5)
        assert handle.raw.api.WaitForSingleObject(child,0)==0
        assert not runtime.terminals and handle.reader.done() and handle.pipe.closed
        final=await handle.inspectActivity();assert final['state']=='idle' and final['revision']>first['revision']
    finally:
        if child is not None:handle.raw.api.CloseHandle(child)
        if handle is not None:await handle.terminate()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_controller_original_screen_and_local_provider_survive_detach_and_unload(tmp_path):
    from types import SimpleNamespace
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.terminal.screen_runtime import TerminalScreenRuntime
    from dsh.api.terminal_controller_authorized import AuthorizedTerminalController
    from scripts.rc022_browser_terminal_probe import Channel
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx);stream=None;handle=None
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
        ctx.set_service('workingDirectory',SimpleNamespace(get=lambda _:str(tmp_path),ensure=lambda agent,signal:asyncio.sleep(0,result=str(tmp_path))))
        ctx.set_service('sandboxPolicy',SimpleNamespace(defaultMode='danger-full-access'))
        controller=AuthorizedTerminalController(ctx,dict(shell=dict(path=os.path.join(os.environ['SystemRoot'],'System32','cmd.exe'),name='cmd',args=['/q']),unattendedTimeoutMs=0))
        agent=SimpleNamespace(id='actual-session',ctx=ctx,session=SimpleNamespace(id='actual-session',header={}))
        await controller.create(agent,dict(id='actual',cols=80,rows=24),AbortController().signal)
        terminal=controller.terminal(agent,'actual');handle=terminal.handle;abort=AbortController()
        stream=terminal.attach(Channel(),controller.config,abort.signal)
        assert (await stream.__anext__())['type']=='snapshot'
        await stream.aclose();stream=None
        assert handle in runtime.terminals
        await handle.write('@echo off\r');await handle.write('echo ACTUAL-NATIVE-SCREEN\r')
        await until(lambda:'ACTUAL-NATIVE-SCREEN' in terminal.readScreen(dict(offset=0,count=100,maxBytes=10000))['text'])
        stream=terminal.attach(Channel(),controller.config,AbortController().signal)
        assert 'ACTUAL-NATIVE-SCREEN' in (await stream.__anext__())['screen']
        await stream.aclose();stream=None
        await controller.dispose()
        assert not controller.owners and not runtime.terminals and not ctx.terminalScreens.engines and not ctx.jsRuntime._workers
        assert handle.raw.job is None and handle.reader.done() and handle.pipe.closed
    finally:
        if stream is not None:await stream.aclose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_abort_identity_before_allocation_and_invalid_argv_type():
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx)
    try:
        reason=RuntimeError('exact cancel');abort=AbortController();abort.abort(reason)
        with pytest.raises(RuntimeError) as caught:await runtime.spawnTerminal(dict(argv=['cmd.exe'],signal=abort.signal))
        assert caught.value is reason and not runtime.terminals
        with pytest.raises(Exception) as caught:await runtime.spawnTerminal(dict(argv=[]))
        assert caught.value.name=='SubprocessError' and caught.value.code=='SUBPROCESS_INVALID_ARGV'
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_output_backpressure_releases_during_termination_without_a_consumer(tmp_path):
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx);handle=None
    try:
        handle=await runtime.spawnTerminal(spec(tmp_path,cols=240,rows=100))
        await handle.write('@echo off\r')
        # WinPTY observes console paint updates. Pace uniquely numbered lines
        # within the real viewport so this test fills the byte queue rather
        # than relying on an unobserved, one-shot console overwrite burst.
        await handle.write('"'+sys.executable+'" -c "import time;[print(str(i)+\'X\'*900,flush=True) or time.sleep(.01) for i in range(600)]"\r')
        try:await until(lambda:handle.bytes>=262144)
        except asyncio.TimeoutError:
            raise AssertionError('Backpressure not reached: bytes='+str(handle.bytes)+' tail='+repr(b''.join(handle.queue)[-300:]))
        assert not handle.reader.done() and not handle.eof
        await asyncio.wait_for(handle.terminate(),5)
        assert handle.reader.done() and handle.eof and handle.pipe.closed and not runtime.terminals
        chunks=[]
        async for chunk in handle.output:chunks.append(chunk)
        assert len(b''.join(chunks))>=262144 and handle.bytes==0
    finally:
        if handle is not None:await handle.terminate()
        await ctx.fiber.dispose()
