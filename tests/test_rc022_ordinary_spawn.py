import asyncio
import errno
import json
from pathlib import Path
import sys

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from dsh.subprocess.ordinary_authorized import validate
from dsh.subprocess.error import SubprocessError

pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='Native Win7 process provider')


def spec(tmp_path,code,stdin='ignore',max_bytes=10000):
    return dict(argv=[sys.executable,'-u','-c',code],cwd=str(tmp_path),graceMs=100,
        stdio=dict(stdin=stdin,stdout=dict(maxBytes=max_bytes),stderr=dict(maxBytes=10000)))


@pytest.mark.asyncio
async def test_actual_large_batch_collectors_and_owned_awaiter_cancel(tmp_path):
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime);runtime=ctx.subprocess
    try:
        code="import sys;data=sys.stdin.buffer.read();sys.stdout.buffer.write(str(len(data)).encode());sys.stderr.buffer.write('你好'.encode('utf-8'))"
        handle=runtime.spawn(spec(tmp_path,code,dict(data='汉'*100000)))
        async def wait():return await handle.done
        waiter=asyncio.create_task(wait());await asyncio.sleep(0);waiter.cancel()
        with pytest.raises(asyncio.CancelledError):await waiter
        assert await handle.done==dict(exitCode=0,signal=None)
        assert handle.collected['stdout'].readFrom(0)['text']=='300000'
        assert handle.collected['stderr'].readFrom(0)['text']=='你好'
        assert handle.stdin is None
    finally:await owner.dispose();await ctx.fiber.dispose()
    assert not runtime.live and not runtime.ordinary_cleanups


@pytest.mark.asyncio
async def test_job_retains_detached_descendant_after_direct_exit(tmp_path):
    from dsh.subprocess.windows_inspector import WindowsProcessInspector
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime);runtime=ctx.subprocess
    child="import time;time.sleep(60)"
    code="import subprocess,sys;child=subprocess.Popen([sys.executable,'-c',%r],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=8);print(child.pid,flush=True)" % child
    try:
        handle=runtime.spawn(spec(tmp_path,code));assert (await handle.done)['exitCode']==0
        pid=int(handle.collected['stdout'].readFrom(0)['text'])
        inspector=WindowsProcessInspector();before=next(item for item in inspector.snapshot().tree(pid) if item['pid']==pid)
        signal=AbortController();signal.abort('probe')
        assert await handle.waitForExit(signal.signal) is False
        assert handle in runtime.live
        raw=handle.raw._proc;original=raw.kill_range
        def failed():raise OSError('injected failed Job termination')
        raw.kill_range=failed
        with pytest.raises(OSError,match='injected'):handle.terminate()
        raw.kill_range=original;handle.terminate();handle.terminate()
        assert await asyncio.wait_for(handle.waitForExit(),5)
        after=inspector.snapshot().tree(pid)
        assert before not in after
    finally:await owner.dispose();await ctx.fiber.dispose()
    assert not runtime.live and not runtime.ordinary_cleanups


@pytest.mark.asyncio
async def test_owner_unload_kills_running_job_and_aborted_launch_publishes_nothing(tmp_path):
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime);runtime=ctx.subprocess
    handle=runtime.spawn(spec(tmp_path,'import time;time.sleep(60)'))
    await owner.dispose();assert await handle.done==dict(exitCode=1,signal=None)
    assert not runtime.live and not runtime.ordinary_cleanups
    await ctx.fiber.dispose()
    controller=AbortController();controller.abort('cancelled')
    request=spec(tmp_path,'');request['signal']=controller.signal
    with pytest.raises(RuntimeError,match='aborted before spawn: cancelled') as caught:validate(request)
    assert caught.value.name=='AbortError'


@pytest.mark.asyncio
async def test_failed_launch_retains_empty_collectors_and_original_error(tmp_path):
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime);runtime=ctx.subprocess
    request=spec(tmp_path,'');request['argv']=[str(tmp_path/'missing.exe')]
    try:
        handle=runtime.spawn(request)
        with pytest.raises(FileNotFoundError):await handle.done
        assert handle.collected['stdout'].readFrom(0)==dict(text='',nextOffset=0,lossy=False)
        assert handle.collected['stderr'].readFrom(0)==dict(text='',nextOffset=0,lossy=False)
        assert await handle.waitForExit()
    finally:await owner.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_assignment_failure_kills_suspended_target_before_any_code(tmp_path,monkeypatch):
    import dsh.sandbox.windows_acl as windows
    import dsh.subprocess.windows_process as process
    from dsh.subprocess.windows_inspector import WindowsProcessInspector
    original_api=windows.WinApi;original_process=process.WindowsJobProcess;allocated=[]
    def api():
        value=original_api();value.AssignProcessToJobObject=lambda *_:0;return value
    class Captured(original_process):
        def __new__(cls,*args,**kwargs):
            value=super().__new__(cls);allocated.append(value);return value
    monkeypatch.setattr(windows,'WinApi',api);monkeypatch.setattr(process,'WindowsJobProcess',Captured)
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime);marker=tmp_path/'must-not-run'
    try:
        handle=ctx.subprocess.spawn(spec(tmp_path,"from pathlib import Path;Path(%r).write_text('ran',encoding='utf-8')" % str(marker)))
        with pytest.raises(OSError):await handle.done
        assert not marker.exists() and allocated[0].pid>0
        assert not WindowsProcessInspector().snapshot().tree(allocated[0].pid)
        assert allocated[0].job is None and allocated[0].process is None
    finally:await owner.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_target_inherits_only_explicit_stdio_handles(tmp_path):
    import os
    import msvcrt
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    read_fd,write_fd=os.pipe();foreign=msvcrt.get_osfhandle(write_fd);os.set_handle_inheritable(foreign,True)
    code="import ctypes as c;from ctypes import wintypes as w;k=c.WinDLL('kernel32',use_last_error=True);k.WriteFile.argtypes=[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.c_void_p];n=w.DWORD();print(k.WriteFile(%s,b'foreign',7,c.byref(n),None),flush=True)" % foreign
    try:
        handle=ctx.subprocess.spawn(spec(tmp_path,code));assert (await handle.done)['exitCode']==0
        assert handle.collected['stdout'].readFrom(0)['text'].strip()=='0'
    finally:
        os.set_handle_inheritable(foreign,False);os.close(write_fd);os.close(read_fd)
        await owner.dispose();await ctx.fiber.dispose()


@pytest.mark.parametrize('grace',[None,False,0,-1,float('inf'),2147483648])
def test_validation_precedes_allocation(grace):
    with pytest.raises(ValueError,match='graceMs'):validate(dict(graceMs=grace,argv=[]))
    with pytest.raises(SubprocessError) as caught:validate(dict(graceMs=1,argv=[]))
    assert caught.value.code=='SUBPROCESS_INVALID_ARGV'
