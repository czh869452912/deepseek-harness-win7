import asyncio
import json
from pathlib import Path
import sys
import pytest
from scripts.rc022_package_view_probe import observe
from dsh.boot.plugin_package_view import view_profile_package


@pytest.mark.asyncio
async def test_owned_package_view_execution_environment_and_deadlines(tmp_path):
    rows={row['name']:row['result'] for row in await observe(tmp_path)}
    assert len(rows)==9
    assert rows['normal']['stdout']['args']==['view','@scope/pkg@^1.0','name','version','dsh','--json','--config.fetch-retries=0']
    assert rows['registry']['stdout']['args'][-2:] == ['--registry=https://corp.example/','--config.fetch-retries=0']
    assert rows['normal']['stdout']['environment']['DSH_PRIVATE_VALUE'] is None
    assert rows['normal']['stdout']['environment']['EXAMPLE_SESSION_TOKEN'] is None
    assert rows['environment']['stdout']['environment']['EXPLICIT_SECRET']=='explicit'
    assert rows['environment']['stdout']['environment']['DSH_PRIVATE_VALUE']=='explicit'
    assert rows['failure']['exitCode']==7 and rows['failure']['stderr']=='registry unavailable'
    assert rows['slow']['timedOut'] and rows['slow']['exitCode'] is None
    assert not rows['cancel']['timedOut'] and rows['cancel']['exitCode'] is None
    assert rows['missing']==dict(launchFailed=True)
    absent=await view_profile_package(str(tmp_path),'pkg',dict(command=str(tmp_path/'absent.exe'),fields=[],timeoutMs=2000))
    assert absent['cause'].code=='ENOENT'


@pytest.mark.asyncio
async def test_package_view_task_cancellation_reaps_child_before_return(tmp_path):
    script=tmp_path/'waiting.py'
    pidfile=tmp_path/'pid.json'
    script.write_text('import json,os,time\nfrom pathlib import Path\nPath('+repr(str(pidfile))+').write_text(json.dumps(os.getpid()),encoding="utf-8")\ntime.sleep(30)\n',encoding='utf-8')
    task=asyncio.create_task(view_profile_package(str(tmp_path),'pkg',dict(command=sys.executable,args=[str(script)],fields=[],timeoutMs=10000)))
    for _ in range(200):
        if pidfile.exists():break
        await asyncio.sleep(.01)
    assert pidfile.exists()
    pid=json.loads(pidfile.read_text(encoding='utf-8'))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    if sys.platform=='win32':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.OpenProcess.restype=ctypes.c_void_p
        process=kernel.OpenProcess(0x100000,False,pid)
        if process:
            kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            try:assert kernel.WaitForSingleObject(process,0)==0
            finally:kernel.CloseHandle(process)
    else:
        import os
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
