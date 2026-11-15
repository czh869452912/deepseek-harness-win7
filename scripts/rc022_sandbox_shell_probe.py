"""Current confined executor against fixed Source with controlled collaborators."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
MODES=('normal','denied','signal','fatal','info','full','sync-runner','async-runner','foreign','prepare-fail','prepare-timeout','prepare-abort')


async def observe():
    from dsh.cordis import Context
    from dsh.shell.executor_current import ENCODING_PREAMBLE
    from dsh.shell.sandbox_current import CurrentSandboxPwshExecutor,runner_spawn_failure,runner_failure,matches_signature
    from dsh.core.abort import AbortController,abort_reason_error
    from dsh.core.cancellation import subscribe_abort
    class Error(Exception):pass
    rows=[]
    for mode in MODES:
        ctx=Context();loop=asyncio.get_running_loop();future=loop.create_future();gate=loop.create_future();calls=[];spawns=[];detaches=[];original=Error('provider failed');stderr='Access is denied' if mode in ('denied','signal') else 'runner: info\nrunner: fatal' if mode=='fatal' else 'runner: info' if mode=='info' else ''
        if mode in ('sync-runner','async-runner'):original.code='ENOENT';original.path='runner';original.syscall='spawn runner'
        elif mode=='foreign':original.code='EMFILE';original.path='runner';original.syscall='spawn runner'
        controller=AbortController();policy=dict(mode='read-only',workspaceRoot=str(WORKSPACE));facts=dict(argv=['runner'],enforcement='partial',denialSignatures=['access is denied'],runnerFailureRules=[dict(fatalSignatures=['runner:','\uFEFF'],informationalLines=['runner: info'],allowedExitCodes=[127])])
        async def confine(argv,selected,signal):
            calls.append(dict(argv0=argv[0],policy=selected,signal=signal is not None))
            if mode=='prepare-fail':raise original
            if mode in ('prepare-timeout','prepare-abort'):await asyncio.shield(gate)
            return facts
        def read(text):return NS(readFrom=lambda offset:dict(text=text.encode('utf-8')[offset:].decode('utf-8'),nextOffset=len(text.encode('utf-8')),lossy=False))
        def spawn(spec):
            spawns.append(dict(argv=[arg.replace(ENCODING_PREAMBLE,'<Win7 UTF8 preamble>') for arg in spec['argv']],cwd=spec['cwd']))
            if mode=='sync-runner':raise original
            def abort(_):
                if not future.done():future.set_exception(abort_reason_error(spec['signal']))
            detaches.append(subscribe_abort(spec.get('signal'),abort))
            return NS(done=future,collected=dict(stdout=read('out'),stderr=read(stderr)),terminate=lambda:future.set_result(dict(exitCode=1,signal=None)))
        ctx.set_service('subprocess',NS(spawn=spawn));ctx.set_service('sandbox',NS(confine=confine));ctx.set_service('sandboxPolicy',NS(defaultMode='read-only',resolve=lambda:policy))
        await ctx.plugin(CurrentSandboxPwshExecutor,dict(cwd=str(WORKSPACE),pwshPath='pwsh-fixture'));shell=ctx.shell
        request=dict(command='command',timeoutMs=5 if mode=='prepare-timeout' else 10000,onExpiry='kill',signal=controller.signal)
        if mode=='full':request['sandboxPolicy']=dict(policy,mode='danger-full-access')
        try:
            pending=asyncio.create_task(shell.execute(shell.resolve(request)))
            if mode=='prepare-abort':
                while not calls:await asyncio.sleep(0)
                controller.abort(original)
            try:process=await pending
            except Exception as error:
                rows.append(dict(name=mode,originalError=error is original,spawns=spawns,calls=calls));continue
            if mode!='prepare-timeout' and mode!='sync-runner':
                if mode in ('async-runner','foreign'):future.set_exception(original)
                else:future.set_result(dict(exitCode=127 if mode in ('fatal','info') else None if mode=='signal' else 3 if mode=='denied' else 0,signal='SIGTERM' if mode=='signal' else None))
            await process.done;projection=process.result()
            row=dict(name=mode,status=process.status,sandbox=process.sandbox,remainingFacts=len(shell.process_facts),sameResult=projection is process.result(),calls=calls,spawns=spawns)
            try:row['result']=await projection
            except Exception as error:row['error']=dict(original=error is original,code=getattr(error,'code',None),message=getattr(error,'message',str(error)))
            rows.append(row)
        finally:
            if not gate.done():gate.set_result(None)
            if not future.done():future.set_result(dict(exitCode=0,signal=None))
            for detach in detaches:detach()
            for _ in range(8):await asyncio.sleep(0)
            await ctx.fiber.dispose()
    errors=[dict(code='ENOENT',syscall='spawn runner',path='runner'),dict(code='EACCES',syscall='spawn',path='runner'),dict(code='ENOENT',syscall='spawn runner'),dict(code='ENOENT',syscall='spawn other',path='runner'),dict(code='ENOENT',syscall='spawn',path='other'),dict(code='EMFILE',syscall='spawn runner'),dict(code='ENOENT',path='runner'),None,'boom']
    rows.append(dict(name='helpers',spawn=[runner_spawn_failure(error,'runner',str(WORKSPACE)) for error in errors],missingCwd=runner_spawn_failure(errors[0],'runner',str(WORKSPACE/'missing')),fatal=runner_failure(127,'runner: info\r\nrunner: fatal',facts['runnerFailureRules']),success=runner_failure(0,'runner: fatal',facts['runnerFailureRules']),signal=matches_signature(None,'Access is denied',facts['denialSignatures'])))
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sandbox_shell.mts','Actual confined PowerShell executor over controlled subprocess/sandbox/policy: mode snapshots and per-call policy, process facts before settlement, denial versus fatal rules, stage-neutral versus runner-specific rejection, full-access bypass, memoized result, preparation deadline/abort and helper evidence matrix.',[Path(__file__).resolve(),ROOT/'dsh/shell/sandbox_current.py',ROOT/'dsh/shell/executor_current.py'],prepare=prepare)
