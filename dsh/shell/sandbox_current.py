"""Current confined PowerShell executor with per-process classification facts."""
import errno
import os
import re
import sys

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.text import trim_js
from dsh.cordis.utils import js_to_string,_UNDEFINED
from dsh.core.cleanup import CleanupPromise
from dsh.jobs.pump import field
from dsh.sandbox.vocabulary import SandboxUnavailableError
from .executor_current import CurrentPwshExecutor


def matches_signature(code,stderr,signatures):
    return code is not None and code!=0 and any(value.lower() in stderr.lower() for value in signatures)


def runner_failure(code,stderr,rules):
    if code is None or code==0:return None
    for rule in rules:
        if 'allowedExitCodes' in rule and code not in rule['allowedExitCodes']:continue
        ignored={value.lower() for value in rule.get('informationalLines',[])}
        signatures=[value.lower() for value in rule['fatalSignatures'] if trim_js(value)]
        for line in re.split(r'\r?\n',stderr):
            lowered=line.lower()
            if lowered not in ignored and any(value in lowered for value in signatures):return line
    return None


def runner_spawn_failure(error,program,cwd):
    if program is None or not os.path.isdir(cwd) or not os.access(cwd,os.X_OK):return False
    code=field(error,'code');path=field(error,'path',_UNDEFINED);syscall=field(error,'syscall')
    if isinstance(error,OSError) and code is None:
        # LEGAL_ADAPTATION: CPython reports errno/filename; CreateProcess omits
        # filename. Only its executable-resolution/permission Win32 errors are
        # attributable after independently checking the caller's cwd.
        return error.errno in (errno.ENOENT,errno.EACCES) and (error.filename==program or (sys.platform=='win32' and error.filename is None and getattr(error,'winerror',None) in (2,5)))
    if code not in ('EACCES','ENOENT') or not isinstance(syscall,str):return False
    exact='spawn '+program
    if path is _UNDEFINED:return syscall==exact
    return isinstance(path,str) and bool(path) and path==program and syscall in ('spawn',exact)


class CurrentSandboxPwshExecutor(CurrentPwshExecutor):
    inject=['subprocess','sandbox','sandboxPolicy']

    def __init__(self,ctx,config=None):
        self.process_facts={};super().__init__(ctx,config);self.mode=ctx.sandboxPolicy.defaultMode

    @property
    def sandboxMode(self):return self.mode

    def resolve(self,request):
        value=super().resolve(request)
        value['sandboxPolicy']=request.get('sandboxPolicy') if request.get('sandboxPolicy') is not None else self.ctx.sandboxPolicy.resolve()
        return value

    async def execute(self,spec):
        policy=spec['sandboxPolicy'];mode=policy['mode']
        if mode=='danger-full-access':
            return self.decorate(await super().execute(spec),lambda result:dict(result,sandbox=dict(mode=mode,denied=False)))
        confined=[None]
        async def prepare(signal):
            facts=await await_callback_result(self.ctx.sandbox.confine(self.argv(spec),dict(policy,mode=mode),signal))
            signal.throwIfAborted();confined[0]=facts;return facts['argv']
        def started(process):self.process_facts[id(process)]=dict(confined[0],mode=mode,workdir=spec['workdir'])
        execution=await self.execute_argv(spec,prepare,started)
        def project(result):
            facts=confined[0]
            if facts is None:return dict(result,sandbox=dict(mode=mode,denied=False))
            failure=runner_failure(result['exitCode'],result['stderr']['text'],facts['runnerFailureRules'])
            if failure is not None:raise SandboxUnavailableError(mode,failure)
            return dict(result,sandbox=dict(mode=mode,denied=matches_signature(result['exitCode'],result['stderr']['text'],facts['denialSignatures']),enforcement=facts['enforcement']))
        def rejected(error):
            signal=spec.get('signal')
            if signal is not None and signal.aborted:signal.throwIfAborted()
            if confined[0] is not None and runner_spawn_failure(error,next(iter(confined[0]['argv']),None),spec['workdir']):raise SandboxUnavailableError(mode,js_to_string(error))
            raise error
        return self.decorate(execution,project,rejected)

    @staticmethod
    def decorate(execution,project,rejected=None):
        base=execution.result;decorated=[None]
        def result():
            if decorated[0] is None:
                async def settle():
                    try:value=await base()
                    except Exception as error:
                        if rejected is not None:return rejected(error)
                        raise
                    return project(value)
                decorated[0]=CleanupPromise(settle())
            return decorated[0]
        execution.result=result;return execution

    def onProcessDone(self,process,stderr,provider_rejected,provider_error=None):
        facts=self.process_facts.pop(id(process),None)
        if facts is not None:
            failed=runner_spawn_failure(provider_error,next(iter(facts['argv']),None),facts['workdir']) if provider_rejected else runner_failure(process.exitCode,stderr,facts['runnerFailureRules']) is not None
            process.sandbox=dict(mode=facts['mode'],denied=not failed and matches_signature(process.exitCode,stderr,facts['denialSignatures']),enforcement=facts['enforcement'],**(dict(runnerFailed=True) if failed else {}))
        super().onProcessDone(process,stderr,provider_rejected,provider_error)
