"""Current PowerShell execution contract over the canonical subprocess service.

The encoding preamble uses PowerShell's Win7-compatible New-Object spelling.
Processes and their descendants belong to ctx.subprocess across executor reloads.
"""
import asyncio
import math
import ntpath
import os
import re
import stat
import sys
from types import SimpleNamespace as NS

from dsh.cordis.awaiting import await_callback_result,start_coroutine
from dsh.cordis.text import JS_WHITESPACE
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.volatile import is_volatile
from dsh.cordis.utils import js_to_string,_UNDEFINED
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortSignal,abort_reason_error
from dsh.core.cancellation import aborted,subscribe_abort
from dsh.core.cleanup import CleanupPromise
from dsh.core.timeout import deadline,timeout_of,clamp_timeout,MAX_TIMER_DELAY_MS
from dsh.jobs.pump import field
from dsh.terminal.grapheme import utf8

DEFAULTS=dict(timeoutMs=120000,maxTimeoutMs=600000,maxOutputBytes=64000,maxSpillBytes=67108864,graceMs=3000)
ENV_OVERRIDES=dict(NO_COLOR='1',PAGER='cat',GIT_PAGER='cat')
ENCODING_PREAMBLE="if ($ExecutionContext.SessionState.LanguageMode -eq 'FullLanguage') { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; $OutputEncoding = New-Object System.Text.UTF8Encoding $false }; "


def windows_join(*parts):
    value=ntpath.normpath(ntpath.join(*parts))
    # Node's win32 normalization protects relative colon-bearing paths from
    # being reinterpreted as a drive/alternate stream by CreateFile.
    if ':' in value and not ntpath.isabs(value) and not re.match(r'^[a-zA-Z]:',value):value='.\\'+value
    return value


def candidate_pwsh_paths(env=None):
    env=os.environ if env is None else env
    candidates=[windows_join(env.get('ProgramFiles','C:\\Program Files'),'PowerShell','7','pwsh.exe')]
    for entry in env.get('PATH','').split(';'):
        entry=re.sub(r'^"|"$','',entry.strip(JS_WHITESPACE))
        if entry:candidates.append(windows_join(entry,'pwsh.exe'))
    candidates.append(windows_join(env.get('SystemRoot','C:\\Windows'),'System32','WindowsPowerShell','v1.0','powershell.exe'))
    return candidates


def resolve_pwsh_path(configured=None,env=None,platform=None):
    if configured is not None and len(configured)>0:return configured
    if (sys.platform if platform is None else platform)=='win32':
        for candidate in candidate_pwsh_paths(env):
            try:
                mode=os.lstat(candidate).st_mode
                if stat.S_ISREG(mode) or stat.S_ISLNK(mode):return candidate
            except OSError:pass
    return 'pwsh'


def final_output(reader):
    read=field(reader,'readFrom')(0)
    return dict(text=field(read,'text'),truncated=field(read,'lossy'),**({} if field(read,'spillPath') is None else dict(spillPath=field(read,'spillPath'))))


class CurrentPwshExecutor(Service):
    inject=['subprocess']
    Config=Schema.object(dict({key:Schema.number().default(value).volatile() for key,value in DEFAULTS.items()},cwd=Schema.string().volatile(),pwshPath=Schema.string().volatile()))

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'shell');self.entries=dict(DEFAULTS,**(config or {}));self.preparations=set()
        self.declared=self.value('pwshPath');self.resolved=resolve_pwsh_path(self.declared)

    def value(self,key):
        value=self.entries.get(key)
        value=value.get() if is_volatile(value) else value
        return None if value is _UNDEFINED else value

    @property
    def sandboxMode(self):return None

    @property
    def pwshPath(self):
        declared=self.value('pwshPath')
        if declared!=self.declared:self.resolved=resolve_pwsh_path(declared);self.declared=declared
        return self.resolved

    def resolve(self,request):
        for key in DEFAULTS:
            value=self.value(key)
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('pwsh-local: '+key+' must be a positive finite number')
        if self.value('graceMs')>MAX_TIMER_DELAY_MS:raise ValueError('pwsh-local: graceMs must be no greater than '+str(MAX_TIMER_DELAY_MS))
        timeout=clamp_timeout(request.get('timeoutMs'),self.value('timeoutMs'),self.value('maxTimeoutMs'),'pwsh-local: request.timeoutMs')
        cap=request.get('stdoutMaxBytes',self.value('maxOutputBytes'))
        if type(cap) not in (int,float) or not math.isfinite(cap) or cap<=0:raise ValueError('pwsh-local: request.stdoutMaxBytes must be a positive finite number')
        result={key:request[key] for key in ('command','signal','stdin','env','dshEnv','sandboxPolicy') if key in request}
        result.update(workdir=request.get('workdir',self.value('cwd') if self.value('cwd') is not None else os.getcwd()),timeoutMs=timeout,stdoutMaxBytes=cap,onExpiry=request.get('onExpiry') or 'kill')
        return result

    def argv(self,spec):return [self.pwshPath,'-NoLogo','-NoProfile','-NonInteractive','-Command',ENCODING_PREAMBLE+spec['command']]

    def spawn_spec(self,spec,signal,argv):
        def collect(size):return dict(maxBytes=size,spill=dict(maxBytes=self.value('maxSpillBytes')))
        env=dict(ENV_OVERRIDES);env.update(spec.get('env') or {});env.update(spec.get('dshEnv') or {})
        stderr = collect(self.value('maxOutputBytes'))
        if sys.platform == 'win32':
            stderr['textEncoding'] = 'powershell'
        return dict(argv=list(argv),cwd=spec['workdir'],stdio=dict(stdin=dict(data=spec['stdin']) if 'stdin' in spec else 'ignore',stdout=collect(spec['stdoutMaxBytes']),stderr=stderr),graceMs=self.value('graceMs'),signal=signal,env=env)

    def execute(self,spec):return self.execute_argv(spec,self.argv(spec))

    def execute_argv(self,spec,argv_or_prepare,on_started=None):
        return CleanupPromise(start_coroutine(self._execute_argv(spec,argv_or_prepare,on_started)))

    async def _execute_argv(self,spec,argv_or_prepare,on_started=None):
        timer=deadline(spec.get('signal'),spec['timeoutMs'],'BASH_TIMEOUT') if spec['onExpiry']=='kill' else None
        signal=timer.signal if timer is not None else spec.get('signal')
        def classify():
            expired=timeout_of(signal,'BASH_TIMEOUT') is not None if timer is not None else False
            return dict(timedOut=expired,aborted=aborted(signal) and not expired)
        disarm=timer.dispose if timer is not None else lambda:None
        argv=[];preparation_timed_out=False
        if callable(argv_or_prepare):
            prep_signal=signal if signal is not None else AbortSignal();cancelled=asyncio.get_running_loop().create_future()
            def cancel(_):
                if not cancelled.done():cancelled.set_exception(abort_reason_error(prep_signal))
            detach=subscribe_abort(prep_signal,cancel)
            async def prepare():
                prep_signal.throwIfAborted();return await await_callback_result(argv_or_prepare(prep_signal))
            preparation=asyncio.create_task(prepare());self.preparations.add(preparation)
            def prepared(task):
                self.preparations.discard(task)
                if not task.cancelled():task.exception()
            preparation.add_done_callback(prepared)
            try:
                completed,_=await asyncio.wait([preparation,cancelled],return_when=asyncio.FIRST_COMPLETED)
                argv=await (cancelled if cancelled in completed else preparation)
                prep_signal.throwIfAborted()
            except Exception:
                if not classify()['timedOut']:disarm();raise
                preparation_timed_out=True
            finally:
                detach()
                if not cancelled.done():cancelled.cancel()
                elif not cancelled.cancelled():cancelled.exception()
        else:argv=argv_or_prepare
        running=None;spawn_error=None
        try:
            if not preparation_timed_out:running=self.ctx.subprocess.spawn(self.spawn_spec(spec,signal,argv))
        except Exception as error:spawn_error=error
        empty=NS(readFrom=lambda _:dict(text='',lossy=False,nextOffset=0))
        collected=field(running,'collected') if running is not None else dict(stdout=empty,stderr=empty)
        if any(field(collected,key) is None for key in ('stdout','stderr')):
            disarm();raise RuntimeError('pwsh-local: subprocess implementation dropped a requested collect stream')
        stdout,stderr=field(collected,'stdout'),field(collected,'stderr')
        state=dict(failure=None,reported=False,stdoutOffset=0,stderrOffset=0,result=None)
        def observed_stderr(offset):
            if state['failure'] is None:return field(stderr,'readFrom')(offset)
            note=utf8(state['failure']['note']);return dict(text=note[min(int(offset),len(note)):].decode('utf-8',errors='replace'),nextOffset=len(note),lossy=False)
        process=NS(status='running',exitCode=None,signal=None,sandbox=None,observed=NS(stdout=stdout,stderr=NS(readFrom=observed_stderr)))
        async def settle():
            try:
                try:
                    if spawn_error is not None:raise spawn_error
                    outcome=dict(exitCode=None,signal=None) if preparation_timed_out else await field(running,'done')
                except Exception as error:
                    if running is not None and (process.status=='killed' or aborted(signal)):
                        process.status='killed';self.onProcessDone(process,field(field(stderr,'readFrom')(0),'text'),False);return
                    process.status='killed'
                    try:detail=js_to_string(error.value) if isinstance(error,ThrownValueError) else js_to_string(error)
                    except Exception:detail='unprintable provider failure'
                    state['failure']=dict(error=error,note='subprocess failed before reporting an outcome: '+detail)
                    self.onProcessDone(process,state['failure']['note'],True,error);return
                if process.status=='running':process.status='killed' if aborted(signal) or field(outcome,'signal') is not None else 'completed'
                process.exitCode=field(outcome,'exitCode');process.signal=field(outcome,'signal');self.onProcessDone(process,field(field(stderr,'readFrom')(0),'text'),False)
            finally:disarm()
        process.done=CleanupPromise(settle())
        def read_output():
            out=field(stdout,'readFrom')(state['stdoutOffset']);err=field(stderr,'readFrom')(state['stderrOffset']);state.update(stdoutOffset=field(out,'nextOffset'),stderrOffset=field(err,'nextOffset'))
            err_text=field(err,'text');failure=state['failure']
            if failure is not None and not state['reported']:
                state['reported']=True;err_text+=('\n' if err_text and not err_text.endswith('\n') else '')+failure['note']
            text=field(out,'text');text+=(('\n' if text and not text.endswith('\n') else '')+'[stderr]\n'+err_text if err_text else '')
            return dict(delta=text,lossy=field(out,'lossy') or field(err,'lossy'),**{name+'SpillPath':field(value,'spillPath') for name,value in [('stdout',out),('stderr',err)] if field(value,'spillPath') is not None})
        def kill():
            if process.status!='running':return False
            process.status='killed'
            if running is not None:field(running,'terminate')()
            return True
        def result():
            if state['result'] is None:
                async def project():
                    await process.done
                    if state['failure'] is not None:raise state['failure']['error']
                    return dict(exitCode=process.exitCode,signal=process.signal,timeoutMs=spec['timeoutMs'],stdout=final_output(stdout),stderr=final_output(stderr),**classify())
                state['result']=CleanupPromise(project())
            return state['result']
        process.readOutput=read_output;process.kill=kill;process.result=result
        if not preparation_timed_out and on_started is not None:on_started(process)
        # Promise publication yields to already queued settlement callbacks.
        await asyncio.sleep(0)
        return process

    def onProcessDone(self,process,stderr,provider_rejected,provider_error=None):pass
