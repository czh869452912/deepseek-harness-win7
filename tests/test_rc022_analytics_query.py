import asyncio
import ctypes
import json
import os
import sys
import threading
from pathlib import Path

import pytest

from dsh.client.analytics_environment_query_current import queryEnvironment
from dsh.core.abort import AbortController
from scripts.rc022_analytics_query_probe import observe

ROOT=Path(__file__).resolve().parents[1]
NODE=ROOT/'.goose/out/rc022-prep-20261114-01/toolchain/node-v24.9.0-win-x64/node.exe'


@pytest.mark.asyncio
async def test_actual_query_outcomes_and_separate_stream_byte_limits(tmp_path):
    rows=await observe(NODE)
    (tmp_path/'analytics-query-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert rows[0]==dict(kind='value',stdout='CPU \u578b\u53f7')
    assert [row['reason'] for row in rows[1:6]]==['query-failed','query-failed','timeout','query-failed','query-failed']
    assert rows[6]==dict(kind='value',stdout='\ufffd\ufffdA\ufffd')
    assert rows[7]['kind']==rows[8]['kind']=='value'
    assert all(row['reason']=='output-limit' for row in rows[9:12])
    assert rows[12]['kind']==rows[13]['kind']=='value'
    assert all(row['reason']=='output-limit' for row in rows[14:17])
    assert rows[17]['kind']=='value'  # 128 bytes on each pipe is valid.
    assert not any(t.name=='analytics-environment-query-reader' for t in threading.enumerate())


@pytest.mark.asyncio
async def test_spawn_exception_is_private_and_contained(monkeypatch):
    def fail(*args,**kwargs):raise MemoryError('private spawn failure')
    monkeypatch.setattr('dsh.client.analytics_environment_query_current.subprocess.Popen',fail)
    assert await queryEnvironment('fixed',[],dict(timeoutMillis=10,maxOutputBytes=128))==dict(kind='missing',reason='query-failed')


@pytest.mark.asyncio
async def test_task_cancellation_waits_for_process_and_pipe_cleanup(tmp_path):
    path=tmp_path/'pid.txt'
    code='import os,time;open(%r,"w").write(str(os.getpid()));time.sleep(60)'%str(path)
    operation=asyncio.create_task(queryEnvironment(sys.executable,['-c',code],dict(timeoutMillis=60000,maxOutputBytes=128)))
    for _ in range(400):
        if path.exists():break
        await asyncio.sleep(.005)
    assert path.exists()
    pid=int(path.read_text(encoding='utf-8'));operation.cancel()
    with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(operation,3)
    assert not any(t.name=='analytics-environment-query-reader' for t in threading.enumerate())
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if handle:
            try:
                code=ctypes.c_ulong();assert kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))
                assert code.value!=259
            finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
    controller=AbortController()
    operation=asyncio.create_task(queryEnvironment(sys.executable,['-c','import time;time.sleep(60)'],
        dict(signal=controller.signal,timeoutMillis=60000,maxOutputBytes=128)))
    await asyncio.sleep(.03);controller.abort()
    assert await asyncio.wait_for(operation,3)==dict(kind='missing',reason='query-failed')
    assert not controller.signal._listeners
