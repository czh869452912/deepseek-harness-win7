import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from dsh.sdk.server import HarnessSdkJsonRpcServer
from scripts.rc022_subagent_fixture import setup
from scripts import rc022_sdk_session_probe as probe


@pytest.mark.asyncio
async def test_actual_resume_and_owned_wait_observations(tmp_path):
    probe.WORKSPACE=tmp_path;(tmp_path/'child').mkdir()
    rows={row['name']:row for row in await probe.observe()}
    assert rows['resume']['result']==dict(value={})
    assert rows['restored']['id']=='persisted'
    assert rows['restored']['cwd']=='<work>\\child'
    assert rows['failure']['result']['error']=='active failure'
    assert rows['after-terminal']['result']==dict(value={})
    assert 'cannot be resumed directly' in rows['resume-child']['result']['error']


@pytest.mark.asyncio
async def test_scheduled_restoration_waits_for_initialize_and_shares_resume(tmp_path):
    fixture=await setup(tmp_path/'sessions',script=[],directory=tmp_path);ctx=fixture.ctx
    seed=await ctx.agents.create(dict(sessionId='stored',agentOptions=dict(provider='script',model='model')))
    seed.agent.session.append('turn/start',dict(turn=1));seed.agent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')));await seed.dispose()
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None))
    first=asyncio.create_task(server.resolve_scheduled_agent('stored'));second=asyncio.create_task(server.resolve_scheduled_agent('stored'))
    try:
        await asyncio.sleep(0);assert not first.done() and not second.done()
        await server.initialize(dict(cwd=str(tmp_path),provider='script',model='model'))
        a,b=await asyncio.gather(first,second);assert a is b and ctx.agents.get('stored') is a
        assert await server.resume(dict(sessionId='stored'))=={}
        assert await server.resolve_scheduled_agent('stored') is a
        with pytest.raises(RuntimeError,match='already open'):await server.resume(dict(sessionId='stored'))
        assert not server.scheduled_sessions and not server.creations
    finally:await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_shutdown_releases_schedule_initialization_wait(tmp_path):
    fixture=await setup(tmp_path/'sessions',script=[],directory=tmp_path);ctx=fixture.ctx
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None))
    pending=asyncio.create_task(server.resolve_scheduled_agent('not-opened'))
    try:
        await asyncio.sleep(0);await server.shutdown()
        with pytest.raises(RuntimeError,match='shutting down'):await pending
        assert not ctx.agents.list() and not server.creations
    finally:await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_resume_repairs_interrupted_final_turn_before_delivery(tmp_path):
    fixture=await setup(tmp_path/'sessions',script=[],directory=tmp_path);ctx=fixture.ctx
    seed=await ctx.agents.create(dict(sessionId='interrupted',agentOptions=dict(provider='script',model='model')))
    seed.agent.session.append('turn/start',dict(turn=1));seed.agent.session.append('step/start',dict(turn=1,step=1));await seed.dispose()
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None))
    try:
        await server.initialize(dict(cwd=str(tmp_path),provider='script',model='model'))
        await server.resume(dict(sessionId='interrupted'))
        agent=server.sessions['interrupted'].agent
        ends=[event for event in agent.session.snapshotEvents() if event['type']=='turn/end']
        assert ends[-1]['data']==dict(turn=1,reason=dict(kind='interrupted'))
        assert await server.wait(dict(sessionId='interrupted'))=={}
    finally:await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_wait_joins_real_managed_child_and_shutdown_drains_tree(tmp_path):
    fixture=await setup(tmp_path/'sessions',directory=tmp_path);ctx=fixture.ctx
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None))
    waiting=None;receipt=None
    try:
        await server.initialize(dict(cwd=str(tmp_path),provider='script',model='model'))
        handle=await server.get_or_create('root');parent=handle.agent
        receipt=await ctx.subagents.startActivation(dict(provider='spawn',label='child',delivery='caller',parent=parent,signal=fixture.signal,prompt=[dict(type='text',text='hang')]))
        waiting=asyncio.create_task(server.wait(dict(sessionId='root')))
        await asyncio.sleep(.05);assert not waiting.done()
        await receipt['dispose']()
        assert await asyncio.wait_for(waiting,5)=={}
        receipt=await ctx.subagents.startActivation(dict(provider='spawn',label='second',delivery='caller',parent=parent,signal=fixture.signal,prompt=[dict(type='text',text='hang')]))
        await server.shutdown()
        assert not ctx.agents.list()
    finally:
        if receipt is not None:await receipt['dispose']()
        await server.shutdown();await ctx.fiber.dispose()
        if waiting is not None:await asyncio.gather(waiting,return_exceptions=True)


@pytest.mark.asyncio
async def test_real_sdk_stdio_cold_resume_and_wait(tmp_path):
    from dsh.sdk.client import create_process_deepseek_harness
    root=Path(__file__).resolve().parents[1]
    runtime=dict(command=sys.executable,args=[str(root/'tests/fixtures/rc022_sdk_directory_runtime.py'),str(tmp_path)],cwd=str(root),environment=lambda:dict(os.environ),description='actual SDK resume',initializeTimeoutMs=10000,requestTimeoutMs=5000,shutdownTimeoutMs=5000,disposeEofGraceMs=5000,disposeGraceMs=1000)
    options=dict(cwd=str(tmp_path),provider='script',model='model')
    (tmp_path/'child').mkdir();first=create_process_deepseek_harness(runtime,options)
    try:assert await first.session('persisted').setWorkingDirectory('child')==str(tmp_path/'child')
    finally:await first.close()
    second=create_process_deepseek_harness(runtime,options)
    try:
        await second.start()
        await second.client.resumeSession('persisted')
        assert await second.session('persisted').getWorkingDirectory()==str(tmp_path/'child')
        assert await second.client.request('session/wait',dict(sessionId='persisted'))=={}
    finally:await second.close()
    for harness in (first,second):
        client=harness.client
        assert client.child.poll()==0 and not client.transport.pending
        assert all(stream.closed for stream in (client.child.stdin,client.child.stdout,client.child.stderr))
