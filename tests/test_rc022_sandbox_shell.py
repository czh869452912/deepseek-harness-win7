import asyncio
import sys
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.sandbox.local import LocalSandboxProvider
from dsh.shell.sandbox_current import CurrentSandboxPwshExecutor
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from scripts import rc022_sandbox_shell_probe as probe


@pytest.mark.asyncio
async def test_per_process_sandbox_facts_and_original_failure_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await probe.observe()}
    assert rows['denied']['sandbox']['denied'] and rows['denied']['result']['sandbox']['denied']
    assert not rows['signal']['sandbox']['denied']
    assert rows['fatal']['sandbox']['runnerFailed'] and not rows['fatal']['sandbox']['denied']
    assert rows['fatal']['error']['code']=='SANDBOX_UNAVAILABLE'
    assert rows['fatal']['error']['message'].endswith('Runner failure: runner: fatal')
    assert rows['info']['result']['exitCode']==127 and 'runnerFailed' not in rows['info']['sandbox']
    for name in ('sync-runner','async-runner'):
        assert rows[name]['sandbox']['runnerFailed'] and rows[name]['error']['code']=='SANDBOX_UNAVAILABLE'
    assert rows['foreign']['error']['original'] and 'runnerFailed' not in rows['foreign']['sandbox']
    assert rows['full']['calls']==[] and rows['full']['result']['sandbox']==dict(mode='danger-full-access',denied=False)
    assert rows['prepare-fail']['originalError'] and rows['prepare-fail']['spawns']==[]
    assert rows['prepare-abort']['originalError'] and rows['prepare-abort']['spawns']==[]
    assert rows['prepare-timeout']['result']['timedOut'] and rows['prepare-timeout']['spawns']==[]
    assert rows['helpers']['spawn']==[True,True,True,False,False,False,False,False,False]
    assert not rows['helpers']['missingCwd']
    assert all(row['remainingFacts']==0 and row['sameResult'] for row in rows.values() if 'remainingFacts' in row)


@pytest.mark.asyncio
async def test_overlapping_executions_keep_their_own_dialect_and_result_waiter(tmp_path):
    ctx=Context();completions=[];originals=[]
    def spawn(spec):
        future=asyncio.get_running_loop().create_future();completions.append(future)
        stderr='first denied' if spec['argv']==['first'] else 'second fatal'
        reader=lambda text:NS(readFrom=lambda offset:dict(text=text[offset:],nextOffset=len(text),lossy=False))
        return NS(done=future,collected=dict(stdout=reader(''),stderr=reader(stderr)),terminate=lambda:None)
    async def confine(argv,policy,signal):
        first='first' in argv[-1]
        return dict(argv=['first' if first else 'second'],enforcement='full' if first else 'partial',denialSignatures=['first denied'] if first else [],runnerFailureRules=[] if first else [dict(fatalSignatures=['second fatal'])])
    policy=dict(mode='read-only',workspaceRoot=str(tmp_path))
    ctx.set_service('subprocess',NS(spawn=spawn));ctx.set_service('sandbox',NS(confine=confine));ctx.set_service('sandboxPolicy',NS(defaultMode='read-only',resolve=lambda:policy))
    await ctx.plugin(CurrentSandboxPwshExecutor,dict(cwd=str(tmp_path)))
    try:
        first=await ctx.shell.execute(ctx.shell.resolve(dict(command='first',onExpiry='none')))
        second=await ctx.shell.execute(ctx.shell.resolve(dict(command='second',onExpiry='none')))
        assert len(ctx.shell.process_facts)==2
        projection=first.result()
        async def wait():return await projection
        waiter=asyncio.create_task(wait());await asyncio.sleep(0);waiter.cancel()
        with pytest.raises(asyncio.CancelledError):await waiter
        completions[1].set_result(dict(exitCode=1,signal=None));await second.done
        assert second.sandbox==dict(mode='read-only',denied=False,enforcement='partial',runnerFailed=True)
        assert len(ctx.shell.process_facts)==1
        completions[0].set_result(dict(exitCode=3,signal=None));await first.done
        assert (await first.result())['sandbox']==dict(mode='read-only',denied=True,enforcement='full')
        assert first.result() is projection and not ctx.shell.process_facts
    finally:
        for future in completions:
            if not future.done():future.set_result(dict(exitCode=0,signal=None))
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_local_provider_observes_abort_before_allocating_capabilities():
    ctx=Context();await ctx.plugin(LocalSandboxProvider);controller=AbortController();reason=RuntimeError('stop preparation');controller.abort(reason)
    try:
        with pytest.raises(RuntimeError) as caught:ctx.sandbox.confine(['unused'],dict(mode='read-only',workspaceRoot='unused'),controller.signal)
        assert caught.value is reason and not ctx.sandbox.temps and not ctx.sandbox.workspaces
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Actual Windows ACL runner and canonical subprocess')
async def test_actual_acl_runner_denies_write_and_full_access_bypasses_provider(tmp_path):
    ctx=Context();await ctx.plugin(AuthorizedLocalSubprocessRuntime);await ctx.plugin(LocalSandboxProvider)
    policy=dict(mode='read-only',workspaceRoot=str(tmp_path));ctx.set_service('sandboxPolicy',NS(defaultMode='read-only',resolve=lambda:policy))
    await ctx.plugin(CurrentSandboxPwshExecutor,dict(cwd=str(tmp_path)));target=tmp_path/'denied.txt'
    command="$ErrorActionPreference = 'Stop'; Set-Content -LiteralPath '"+str(target).replace("'","''")+"' -Value 'payload' -Encoding UTF8"
    try:
        process=await ctx.shell.execute(ctx.shell.resolve(dict(command=command,timeoutMs=10000)))
        result=await asyncio.wait_for(process.result(),15)
        assert result['exitCode']!=0 and not target.exists(),result
        assert result['sandbox']['denied'] and result['sandbox']['enforcement']=='partial',result['stderr']['text']
        assert process.sandbox['denied'] and not ctx.shell.process_facts
        full=await ctx.shell.execute(ctx.shell.resolve(dict(command=command,timeoutMs=10000,sandboxPolicy=dict(policy,mode='danger-full-access'))))
        result=await asyncio.wait_for(full.result(),15)
        assert result['exitCode']==0 and target.read_text(encoding='utf-8-sig').strip()=='payload'
        assert result['sandbox']==dict(mode='danger-full-access',denied=False)
        assert not ctx.subprocess.live
    finally:await ctx.fiber.dispose()
