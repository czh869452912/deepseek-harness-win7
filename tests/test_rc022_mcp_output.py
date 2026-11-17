import asyncio
import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.mcp.client_current import CurrentSdkClient, CurrentProtocolError
from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
from dsh.mcp.output_validator_current import CurrentOutputValidator
from scripts import rc022_mcp_output_probe as corpus
from scripts import rc022_mcp_server_probe_probe as peer


@pytest.mark.asyncio
async def test_schema_dialects_cache_override_and_pre_request_compile_isolation():
    rows=await corpus.observe()
    assert len(rows)==20
    assert rows[1]['rows'][0]['error']['code']==-32602
    assert rows[1]['rows'][1]['value']['structuredContent']==dict(x=2)
    assert rows[1]['rows'][7]['error']['code']==-32600
    assert all('value' in row for row in rows[1]['rows'][8:])
    for index in (12,13,14):
        assert all('error' in row for row in rows[index]['rows'])
        assert len(rows[index]['requests'])==1
    assert 'value' in rows[16]['rows'][0]
    assert 'value' in rows[17]['rows'][0] and 'error' in rows[17]['rows'][1]
    assert all('value' in row for row in rows[18]['rows'])
    assert 'value' in rows[19]['rows'][0] and 'error' in rows[19]['rows'][1]


@pytest.mark.asyncio
async def test_actual_http_invalid_structured_result_and_worker_reaping(tmp_path):
    peer.prepare(tmp_path)
    client=CurrentSdkClient()
    try:
        await client.connect(CurrentStreamableHttpMcpTransport(peer.URL+'/modern-output'))
        await client.listTools()
        assert (await client.callTool(dict(name='a',arguments=dict(answer=3))))['structuredContent']==dict(answer=3)
        with pytest.raises(CurrentProtocolError,match='data/answer must be integer') as caught:
            await client.callTool(dict(name='a',arguments=dict(answer='bad')))
        assert caught.value.code==-32602
        process=client._output_validator.process
        await client.close()
        assert process.returncode==0
        assert client._output_validator.jobs==set()
    finally:
        await client.close()
        peer.stop_peer()


@pytest.mark.asyncio
async def test_cancelled_spawn_observer_and_close_observer_leave_one_owned_reap(monkeypatch):
    entered,release=asyncio.Event(),asyncio.Event()
    original=asyncio.create_subprocess_exec
    async def held(*args,**kwargs):
        entered.set();await release.wait()
        return await original(*args,**kwargs)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',held)
    worker=CurrentOutputValidator()
    observer=asyncio.create_task(worker.observe(dict(schema=dict(type='object'),value={})))
    await entered.wait();observer.cancel()
    with pytest.raises(asyncio.CancelledError):await observer
    close=worker.close()
    async def wait():await close
    departed=asyncio.create_task(wait());await asyncio.sleep(0);departed.cancel()
    with pytest.raises(asyncio.CancelledError):await departed
    release.set();await close
    assert worker.process.returncode==0 and not worker.jobs


def test_x86_validator_matches_original_paired_x64_corpus():
    executable=os.environ.get('DSH_TEST_X86_PYTHON')
    if not executable:pytest.skip('explicit x86 Python fixture not configured')
    script='import asyncio,ctypes,json,os,sys;sys.path.insert(0,os.getcwd());from scripts.rc022_mcp_output_probe import observe;assert ctypes.sizeof(ctypes.c_void_p)==4;print(json.dumps(asyncio.run(observe()),ensure_ascii=True))'
    result=subprocess.run([executable,'-c',script],cwd=str(Path(__file__).resolve().parents[1]),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    assert result.returncode==0,result.stderr.decode('utf-8',errors='replace')[-1000:]
    assert json.loads(result.stdout)==asyncio.run(corpus.observe())
