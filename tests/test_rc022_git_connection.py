import asyncio
import json
from pathlib import Path
import sys
import pytest
from scripts.rc022_git_connection_probe import observe
from dsh.boot.plugin_git_connection import check_github_connection,check_git_connection
from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.plugin_package_view import _execute_package_query
from dsh.core.abort import AbortController


@pytest.mark.asyncio
async def test_actual_git_preflight_transports_logs_and_deadlines(tmp_path):
    rows=await observe(tmp_path)
    actual={row['mode']:row for row in rows if row['kind']=='actual'}
    assert actual['http-success']['result'].startswith('https://')
    assert len(actual['http-success']['commands'])==1
    assert actual['ssh-success']['result'].startswith('git+ssh://')
    assert len(actual['ssh-success']['commands'])==2
    assert actual['both-fail']['result'].startswith('https://')
    assert len(actual['both-fail']['commands'])==2
    assert len(actual['transport-cancel']['commands'])==1
    assert actual['check-success']['result'] is None
    assert actual['check-http']['result']['kind']=='network'
    assert actual['check-auth']['result']['kind']=='unknown'
    assert actual['check-credentials']['result']['argv'][-2]=='https://git.example/team/repo.git'
    assert actual['check-tail']['result']['truncated']
    assert actual['check-tail']['result']['hasDiagnostic']
    assert actual['check-timeout']['result']['timedOut'] and actual['check-timeout']['result']['timeoutDiagnostic']
    assert actual['check-cancel']['result']['kind']=='unknown'
    assert actual['github-skip']['result'] is None and actual['github-skip']['commands']==[]
    assert actual['github-subdomain']['result']['kind']=='network'


@pytest.mark.asyncio
async def test_streaming_stderr_retains_bytes_beyond_returned_output_bound(tmp_path):
    script=tmp_path/'writer.py';script.write_text('import sys\nsys.stdout.buffer.write(b"ignored"*200000)\nsys.stdout.flush()\nsys.stderr.buffer.write(b"x"*200000+b"0123456789")\nsys.exit(7)\n',encoding='utf-8')
    path=tmp_path/'git.log'
    with path.open('wb') as stream:
        result=await _execute_package_query(str(tmp_path),[sys.executable,str(script)],dict(timeoutMs=5000,_stderrFile=stream))
    assert result['exitCode']==7
    assert path.read_bytes()==b'x'*200000+b'0123456789'
    assert result['stdout']==result['stderr']==''


@pytest.mark.asyncio
async def test_discarded_streams_drain_beyond_pipe_capacity(tmp_path):
    script=tmp_path/'discard.py'
    script.write_text('import sys\nsys.stdout.buffer.write(b"x"*2000000)\nsys.stdout.flush()\nsys.stderr.buffer.write(b"y"*2000000)\nsys.stderr.flush()\n',encoding='utf-8')
    result=await _execute_package_query(str(tmp_path),[sys.executable,str(script)],dict(timeoutMs=5000,_discardOutput=True))
    assert result['exitCode']==0 and not result['timedOut']
    assert result['stdout']==result['stderr']==''


@pytest.mark.asyncio
async def test_github_gate_does_not_create_assets_for_unrelated_specs(tmp_path):
    options=dict(timeoutMs=100,outputBytes=10,signal=AbortController().signal)
    for spec in ('pkg','https://gitlab.com/org/repo.git','https://notgithub.com/org/repo.git'):
        assert await check_github_connection(parse_install_spec(spec),str(tmp_path),options) is None
    assert list(tmp_path.iterdir())==[]


@pytest.mark.asyncio
async def test_missing_git_is_not_misclassified_as_network(tmp_path):
    result=await check_git_connection(parse_install_spec('github:org/repo'),str(tmp_path),
        dict(timeoutMs=500,outputBytes=4096,signal=AbortController().signal,env=dict(PATH=str(tmp_path))))
    assert result['exitCode']==127 and result['kind']=='unknown'
    assert result['output'] and Path(result['logPath']).read_text(encoding='utf-8')==result['output']


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Win7 Job process ownership observation')
async def test_cancellation_joins_parent_and_descendant_with_open_stream(tmp_path):
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    pidfile=tmp_path/'pids.json';script=tmp_path/'tree.py'
    script.write_text('import json,os,subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\nPath('+repr(str(pidfile))+').write_text(json.dumps([os.getpid(),child.pid]),encoding="utf-8")\nsys.stderr.write("started\\n");sys.stderr.flush()\ntime.sleep(30)\n',encoding='utf-8')
    with (tmp_path/'tree.log').open('wb') as stream:
        task=asyncio.create_task(_execute_package_query(str(tmp_path),[sys.executable,str(script)],dict(timeoutMs=10000,_stderrFile=stream)))
        for _ in range(200):
            if pidfile.exists():break
            await asyncio.sleep(.01)
        assert pidfile.exists()
        handles=[kernel.OpenProcess(0x100000,False,pid) for pid in json.loads(pidfile.read_text(encoding='utf-8'))]
        assert all(handles)
        try:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            statuses=[kernel.WaitForSingleObject(handle,0) for handle in handles]
            (tmp_path/'git-cancellation-observations.json').write_text(json.dumps(dict(pids=json.loads(pidfile.read_text(encoding='utf-8')),wait_statuses=statuses)),encoding='utf-8')
            assert statuses==[0,0]
        finally:
            for handle in handles:kernel.CloseHandle(handle)
    assert (tmp_path/'tree.log').read_bytes()==b'started\r\n'
