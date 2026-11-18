import asyncio
import sys

import pytest

from dsh.core.abort import AbortController,NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.jobs.current import CurrentLocalJobRegistry
from dsh.jobs.tool_current import CurrentToolJobs
from dsh.shell.executor_current import CurrentPwshExecutor
from dsh.shell.tool_current import CurrentToolPwsh
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from scripts import rc022_pwsh_tool_probe as probe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_current_tool_dynamic_registration_promotion_and_consuming_output(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows['definitions']['value'])==6
    assert rows['foreground-only']['value']['value']['exitCode']==3
    assert rows['registered-fast']['jobs']==[]
    assert rows['promoted']['value']['value']['output']=='head'
    assert rows['promoted']['ui']['chunks'][0]['text']=='head'
    assert ''.join(chunk['text'] for chunk in rows['after-promotion']['read']['chunks'])=='tail'
    assert rows['background-killed']['read']['job']['status']=='killed'
    assert rows['prepare-timeout']['value']['value']['timedOut']
    assert rows['prepare-timeout']['jobs']==[]
    assert rows['admission-fallback']['value']['value']['timedOut']
    assert not rows['unloaded-registry']['background']


async def runtime(tmp_path,config=None):
    fixture=await setup(tmp_path/'sessions',script=[],directory=tmp_path);ctx=fixture.ctx
    await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    await ctx.plugin(CurrentPwshExecutor,dict(cwd=str(tmp_path)))
    from types import SimpleNamespace
    ctx.set_service('shellEnv',SimpleNamespace(collect=lambda _:{}))
    await ctx.plugin(CurrentToolPwsh,config or {})
    await ctx.plugin(CurrentLocalJobRegistry,dict(pumpPollMs=5))
    await ctx.plugin(CurrentToolJobs,dict(completionDelivery='quiet'))
    lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='model')))
    async def call(name,args,signal=NEVER_ABORTED):
        return await ctx.tools.execute(ToolExecutionInput('call',name,args,agent=lease.agent,signal=signal))
    return ctx,lease,call


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Actual canonical PowerShell/Windows Job integration')
async def test_actual_powershell_promotes_then_job_tools_read_only_remaining_output(tmp_path):
    ctx,lease,call=await runtime(tmp_path)
    try:
        result=await asyncio.wait_for(call('pwsh',dict(command="[Console]::Write('head'); Start-Sleep -Seconds 4; [Console]::Write('tail')",description='Write output before and after waiting',timeoutMs=2000)),10)
        assert not result.is_error and result.value['kind']=='promoted'
        identity=result.value['jobId'];assert result.value['output']=='head'
        assert ''.join(chunk['text'] for chunk in ctx.jobs.readAt(identity,0,lease.agent.id)['chunks'])=='head'
        final=await asyncio.wait_for(call('job_output',dict(job_id=identity,wait=True,timeout_ms=10000)),15)
        assert not final.is_error and final.value['text']=='tail' and final.value['job']['status']=='completed'
        again=await call('job_output',dict(job_id=identity))
        assert again.value['text']==''
        # The subprocess owner releases its managed range after direct done,
        # matching Source's separate waitForExit continuation.
        await asyncio.wait_for(asyncio.gather(*ctx.subprocess.ordinary_cleanups),3)
        assert not ctx.subprocess.live
    finally:await lease.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Actual canonical PowerShell/Windows Job integration')
async def test_actual_background_kill_and_foreground_abort_join_owned_process(tmp_path):
    ctx,lease,call=await runtime(tmp_path)
    try:
        result=await call('pwsh',dict(command='Start-Sleep -Seconds 30',description='Wait for explicit cancellation',run_in_background=True))
        assert not result.is_error and result.value['kind']=='background'
        identity=result.value['jobId']
        for _ in range(200):
            if ctx.subprocess.live:break
            await asyncio.sleep(.01)
        assert ctx.subprocess.live
        killed=await call('job_kill',dict(job_id=identity));assert not killed.is_error
        await ctx.jobs.wait(identity,10000,lease.agent.id)
        await asyncio.wait_for(asyncio.gather(*ctx.subprocess.ordinary_cleanups),3)
        assert ctx.jobs.get(identity,lease.agent.id)['status']=='killed' and not ctx.subprocess.live
        ctx.jobs.remove(identity,lease.agent.id)
        controller=AbortController()
        pending=asyncio.create_task(call('pwsh',dict(command='Start-Sleep -Seconds 30',description='Wait until the caller aborts',timeoutMs=10000),controller.signal))
        for _ in range(200):
            if ctx.subprocess.live:break
            await asyncio.sleep(.01)
        assert ctx.subprocess.live;controller.abort()
        stopped=await asyncio.wait_for(pending,10)
        assert stopped.is_error and 'tool call aborted' in stopped.content[0]['text']
        await asyncio.wait_for(asyncio.gather(*ctx.subprocess.ordinary_cleanups),3)
        assert not ctx.subprocess.live and ctx.jobs.list(lease.agent.id)==[]
        assert not controller.signal._listeners
    finally:await lease.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disabled_background_and_invalid_arguments_fail_before_shell_launch(tmp_path):
    ctx,lease,call=await runtime(tmp_path,dict(enableRunInBackground=False))
    try:
        assert 'run_in_background' not in ctx.tools.get('pwsh').parameters['properties']
        for args in (dict(command=' ',description='Nonempty description'),dict(command='unused',description=' '),dict(command='unused',description='Nonempty description',timeoutMs=0)):
            result=await call('pwsh',args)
            assert result.is_error and not ctx.subprocess.live
    finally:await lease.dispose();await ctx.fiber.dispose()
