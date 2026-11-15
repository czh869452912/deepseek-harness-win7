"""Canonical PowerShell execution lifecycle over a controlled subprocess seam."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from dsh.cordis import Context
    from dsh.shell.executor_current import CurrentPwshExecutor,candidate_pwsh_paths
    from dsh.core.abort import AbortController,abort_reason_error
    from dsh.core.cancellation import subscribe_abort
    rows=[]
    class Error(Exception):pass
    for mode in ('normal','sync-failure','async-failure','kill','abort','timeout','none','prepare-timeout','prepare-abort'):
        ctx=Context();future=asyncio.get_running_loop().create_future();out=['你好'];err=['err'];calls=[];detaches=[];original=Error('provider failed');kills=[];gate=asyncio.get_running_loop().create_future();on_started=[]
        def reader(parts):
            def read(offset):
                data=''.join(parts).encode('utf-8');return dict(text=data[offset:].decode('utf-8',errors='replace'),nextOffset=len(data),lossy=False)
            return NS(readFrom=read)
        def spawn(spec):
            calls.append({key:spec[key] for key in ('argv','cwd','stdio','graceMs','env')})
            if mode=='sync-failure':raise original
            def terminated():
                kills.append('kill')
                if not future.done():future.set_exception(original)
            def cancel(_):
                if not future.done():future.set_exception(abort_reason_error(spec['signal']))
            detaches.append(subscribe_abort(spec.get('signal'),cancel))
            return NS(done=future,terminate=terminated,collected=dict(stdout=reader(out),stderr=reader(err)))
        ctx.set_service('subprocess',NS(spawn=spawn));await ctx.plugin(CurrentPwshExecutor,dict(pwshPath='fake',cwd='C:/fixed',maxOutputBytes=32));shell=ctx.shell;controller=AbortController()
        spec=shell.resolve(dict(command='test',timeoutMs=5 if mode in ('timeout','none','prepare-timeout') else 10000,onExpiry='none' if mode in ('none','kill','normal','sync-failure','async-failure') else 'kill',signal=controller.signal,env=dict(PAGER='less',NO_COLOR='0'),dshEnv=dict(PAGER='managed'),stdin='input'))
        async def prepare(signal):await gate;return ['prepared']
        try:
            if mode.startswith('prepare-'):
                pending=shell.execute_argv(spec,prepare,on_started.append)
                if mode=='prepare-abort':controller.abort(original)
                try:
                    process=await pending;result=await process.result();rows.append(dict(name=mode,result=result,started=len(on_started),spawns=len(calls)))
                except Exception as error:rows.append(dict(name=mode,originalError=error is original,spawns=len(calls)))
                gate.set_result(None)
                for _ in range(5):await asyncio.sleep(0)
                continue
            process=await shell.execute_argv(spec,['fake','arg'],on_started.append);initial=process.status
            if mode=='normal':
                before=process.readOutput();observed=process.observed.stdout.readFrom(2);again=process.readOutput();out.append('tail');future.set_result(dict(exitCode=5,signal=None));await process.done
                result=process.result();rows.append(dict(name=mode,initial=initial,before=before,observed=observed,again=again,after=process.readOutput(),result=await result,sameResult=result is process.result(),calls=calls,started=len(on_started)))
            elif mode in ('sync-failure','async-failure'):
                if mode=='async-failure':future.set_exception(original)
                await process.done
                try:await process.result()
                except Exception as error:failure=error is original
                rows.append(dict(name=mode,initial=initial,status=process.status,originalError=failure,observed1=process.observed.stderr.readFrom(0),observed2=process.observed.stderr.readFrom(0),first=process.readOutput(),second=process.readOutput()))
            else:
                if mode in ('kill','none'):
                    if mode=='none':await asyncio.sleep(.015)
                    before=process.status;first=process.kill();second=process.kill()
                elif mode=='abort':controller.abort(original)
                await process.done
                rows.append(dict(name=mode,status=process.status,result=await process.result(),kills=kills,**(dict(before=before,first=first,second=second) if mode in ('kill','none') else {})))
        finally:
            if not gate.done():gate.set_result(None)
            if not future.done():future.set_result(dict(exitCode=0,signal=None))
            for detach in detaches:detach()
            await ctx.fiber.dispose()
    rows.append(dict(name='candidates',value=candidate_pwsh_paths(dict(ProgramFiles='C:/Program Files',SystemRoot='D:/Windows',PATH=' "C:/one" ; ; C:/two/../bin ;""C:/quoted""'))))
    if WORKSPACE is not None:
        from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
        ctx=Context();await ctx.plugin(AuthorizedLocalSubprocessRuntime);await ctx.plugin(CurrentPwshExecutor,dict(cwd=str(WORKSPACE),maxOutputBytes=8))
        try:
            process=await ctx.shell.execute(ctx.shell.resolve(dict(command="[Console]::Write(('汉' * 100)); exit 5",timeoutMs=10000)));result=await process.result();output=result['stdout']
            rows.append(dict(name='actual-pwsh',result={key:result[key] for key in ('exitCode','signal','timedOut','aborted','timeoutMs')},stdout=dict(text=output['text'],truncated=output['truncated'],full=Path(output['spillPath']).read_text(encoding='utf-8')),stderr=result['stderr']))
        finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_shell_execution.mts','Actual current PowerShell executor with controlled canonical subprocess: retained execution handle, non-consuming observed readers, independent result identity, provider failure note/original error, kill and first-cause timeout/abort classification, no-expiry execution, asynchronous preparation timeout/abort and environment precedence. Windows candidate ordering and real PowerShell UTF8 raw-byte truncation/full spill/nonzero exit are paired. Runtime preamble deliberately remains Win7-compatible New-Object spelling.',[Path(__file__).resolve(),ROOT/'dsh/shell/executor_current.py'],prepare=prepare,node_args=['--expose-internals'])
