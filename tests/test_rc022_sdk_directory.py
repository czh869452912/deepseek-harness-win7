import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from dsh.sdk.server import HarnessSdkJsonRpcServer
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_server_directory_events_recovery_and_rpc_admission(tmp_path):
    from scripts import rc022_sdk_directory_probe as probe
    (tmp_path/'child').mkdir();probe.WORKSPACE=tmp_path
    rows={row['name']:row for row in await probe.observe()}
    assert rows['before-get']['agents']==[]
    assert rows['relative']['result']==dict(value=dict(cwd='<work>\\child'))
    assert rows['isolation']['result']==dict(value=dict(cwd='<work>'))
    assert rows['recovered']['result']==dict(value=dict(cwd='<work>'))
    assert rows['durable']['origin']=='<work>' and rows['durable']['current']=='<work>\\child'
    assert [change['cwd'] for change in rows['durable']['changes']]==['<work>\\child','<work>','<work>\\child']
    assert rows['stale']['result']['error']=='session agent was disposed outside the server: a'
    assert rows['concurrent']['agents']==['b','c']


@pytest.mark.asyncio
async def test_actual_sdk_client_plugin_and_server_over_owned_child_stdio(tmp_path):
    from dsh.sdk.client import create_process_deepseek_harness
    root=Path(__file__).resolve().parents[1];(tmp_path/'child').mkdir()
    runtime=dict(command=sys.executable,args=[str(root/'tests/fixtures/rc022_sdk_directory_runtime.py'),str(tmp_path)],
        cwd=str(root),environment=lambda:dict(os.environ),description='actual SDK directory plugin',initializeTimeoutMs=10000,requestTimeoutMs=5000,
        shutdownTimeoutMs=5000,disposeEofGraceMs=5000,disposeGraceMs=1000)
    harness=create_process_deepseek_harness(runtime,dict(cwd=str(tmp_path),provider='script',model='model'))
    try:
        a=harness.session('a');b=harness.session('b')
        assert await a.getWorkingDirectory()==str(tmp_path)
        assert await a.setWorkingDirectory('child')==str(tmp_path/'child')
        assert await b.getWorkingDirectory()==str(tmp_path)
        (tmp_path/'child').rmdir()
        assert await a.getWorkingDirectory()==str(tmp_path)
    finally:await harness.close()
    client=harness.client
    assert client.child.poll()==0 and not client.transport.pending
    assert all(stream.closed for stream in (client.child.stdin,client.child.stdout,client.child.stderr))
    assert client.monitor.done() and client.input.task.done() and client.stderr_input.task.done()


@pytest.mark.asyncio
async def test_concurrent_rpc_reuses_creation_and_shutdown_retires_agent_before_late_change(tmp_path):
    fixture=await setup(tmp_path/'sessions',script=[],directory=tmp_path);ctx=fixture.ctx
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None));entered=asyncio.Event();release=asyncio.Event()
    original=ctx.workingDirectory.set;changing=shutdown=None
    try:
        await server.initialize(dict(cwd=str(tmp_path),provider='script',model='model'))
        values=await asyncio.gather(*(server.getWorkingDirectory(dict(sessionId='one')) for _ in range(3)))
        assert values==[dict(cwd=str(tmp_path))]*3 and len(ctx.agents.list())==1
        async def held(agent,path,signal=None):entered.set();await release.wait();return await original(agent,path,signal)
        ctx.workingDirectory.set=held
        changing=asyncio.ensure_future(server.setWorkingDirectory(dict(sessionId='one',path='.')))
        await entered.wait();shutdown=asyncio.ensure_future(server.shutdown());await shutdown
        release.set()
        with pytest.raises(Exception):await changing
        assert ctx.agents.get('one') is None
        with pytest.raises(RuntimeError,match='shutting down'):await server.getWorkingDirectory(dict(sessionId='new'))
    finally:
        release.set()
        await asyncio.gather(*(task for task in (changing,shutdown) if task is not None),return_exceptions=True)
        ctx.workingDirectory.set=original;await server.shutdown();await ctx.fiber.dispose()
