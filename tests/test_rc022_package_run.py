import asyncio
import json
from pathlib import Path
import sys
import pytest
from dsh.boot.plugin_package_run import run_package_process
from dsh.core.abort import AbortController
from scripts.rc022_package_run_probe import observe


@pytest.mark.asyncio
async def test_actual_package_runs_logs_callbacks_bounds_and_silence(tmp_path):
    rows={row['mode']:row for row in await observe(tmp_path)}
    assert all(row['recordRemoved'] for row in rows.values())
    assert rows['success']['result']['exitCode']==0
    assert rows['success']['log']=='installed\r\n' if sys.platform=='win32' else rows['success']['log']=='installed\n'
    assert rows['failure']['result']['exitCode']==7
    assert rows['large']['result']['output']=='7890123456789'
    assert rows['large']['result']['truncated']
    assert rows['unicode']['log']=='abc\u4e2d'*1000
    assert rows['progress']['result']['exitCode']==0 and 'timedOut' not in rows['progress']['result']
    assert rows['idle']['result']['timedOut']
    assert 'printed nothing for 500ms' in rows['idle']['result']['output']
    assert rows['cancel']['result']['exitCode']!=0


@pytest.mark.asyncio
async def test_pre_cancel_never_starts_or_records_a_process(tmp_path):
    marker=tmp_path/'must-not-exist';script=tmp_path/'program.py'
    script.write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("ran",encoding="utf-8")\n',encoding='utf-8')
    control=AbortController();control.abort()
    result=await run_package_process(str(tmp_path),[sys.executable,str(script)],dict(outputBytes=4096,signal=control.signal))
    assert result['exitCode']==1 and result['output']
    assert not marker.exists() and not (tmp_path/'.plugin-manager/run.json').exists()


@pytest.mark.asyncio
async def test_foreign_run_record_is_never_overwritten(tmp_path):
    path=tmp_path/'.plugin-manager/run.json';path.parent.mkdir();path.write_bytes(b'foreign record')
    with pytest.raises(RuntimeError,match='must be admitted'):
        await run_package_process(str(tmp_path),[sys.executable,'-c','print(1)'],dict(outputBytes=100))
    assert path.read_bytes()==b'foreign record'
    assert list(path.parent.iterdir())==[path]


@pytest.mark.asyncio
async def test_output_observer_failure_stops_run_and_retains_log(tmp_path):
    script=tmp_path/'writer.py';script.write_text('import time\nprint("start",flush=True)\ntime.sleep(30)\n',encoding='utf-8')
    def fail(text,stream):raise RuntimeError('observer failed')
    with pytest.raises(RuntimeError,match='observer failed'):
        await run_package_process(str(tmp_path),[sys.executable,str(script)],dict(outputBytes=100,onOutput=fail))
    assert not (tmp_path/'.plugin-manager/run.json').exists()
    assert next((tmp_path/'.plugin-manager/logs').glob('*/pnpm.log')).read_bytes().startswith(b'start')


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Win7 Job process handles')
@pytest.mark.parametrize('ending',['cancel','parent-exit'])
async def test_owned_tree_stops_before_run_record_is_removed(tmp_path,ending):
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    pidfile=tmp_path/'pids.json';script=tmp_path/'tree.py'
    script.write_text('import json,os,subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\nPath('+repr(str(pidfile))+').write_text(json.dumps([os.getpid(),child.pid]),encoding="utf-8")\nprint("started",flush=True)\ntime.sleep('+('0.5' if ending=='parent-exit' else '30')+')\n',encoding='utf-8')
    task=asyncio.create_task(run_package_process(str(tmp_path),[sys.executable,str(script)],dict(outputBytes=4096)))
    for _ in range(200):
        if pidfile.exists() and (tmp_path/'.plugin-manager/run.json').exists():break
        await asyncio.sleep(.01)
    assert pidfile.exists() and (tmp_path/'.plugin-manager/run.json').exists()
    pids=json.loads(pidfile.read_text(encoding='utf-8'));handles=[kernel.OpenProcess(0x100000,False,pid) for pid in pids]
    assert all(handles)
    try:
        if ending=='cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        else:
            result=await task
            assert result['exitCode']==0
            assert 'output was cut short' in result['output']
        assert all(kernel.WaitForSingleObject(handle,0)==0 for handle in handles)
        assert not (tmp_path/'.plugin-manager/run.json').exists()
    finally:
        for handle in handles:kernel.CloseHandle(handle)
