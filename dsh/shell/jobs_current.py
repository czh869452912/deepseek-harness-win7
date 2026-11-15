"""Current shell-to-job bridge; preparation remains job-owned and observable."""
import asyncio
from types import SimpleNamespace as NS

from dsh.cordis.awaiting import start_coroutine,await_callback_result
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.jobs.pump import field

HINT='[sandbox: escalation available — retry this exact command once with sandbox_permissions (the narrowest wider mode that suffices) + justification; the approval prompt asks the user]'


def sandbox_notes(sandbox,escalation_modes=()):
    if sandbox is None:return []
    if field(sandbox,'runnerFailed'):
        return ['[sandbox: the sandbox runner itself failed under %s mode — the command did not run; this is a sandbox problem, not a command failure]' % field(sandbox,'mode')]
    if not field(sandbox,'denied'):return []
    return ['[sandbox: file access denied under %s mode]' % field(sandbox,'mode')]+([HINT] if escalation_modes else [])


def process_outcome(process,escalation_modes=()):
    signal=field(process,'signal');code=field(process,'exitCode')
    result=dict(status='killed',detail='signal: '+signal if signal is not None else 'killed before exit') if field(process,'status')=='killed' else dict(status='completed',detail='exit code: '+js_to_string(0 if code is None else code))
    notes=sandbox_notes(field(process,'sandbox'),escalation_modes)
    if notes:result['detail']+='; '+' '.join(notes)
    return result


def process_sources(get_process):
    def source(channel):
        def read(offset):
            process=get_process()
            return dict(text='',nextOffset=offset,lossy=False) if process is None else field(field(field(process,'observed'),channel),'readFrom')(offset)
        return dict(channel=channel,read=read)
    return [source('stdout'),source('stderr')]


def ring_delta(chunks):
    out=''.join(chunk['text'] for chunk in chunks if chunk.get('channel')!='stderr')
    err=''.join(chunk['text'] for chunk in chunks if chunk.get('channel')=='stderr')
    return out+(('\n' if out and not out.endswith('\n') else '')+'[stderr]\n'+err if err else '')


def process_job(start,outcome):
    controller=AbortController();state=dict(process=None,failure=None)
    async def run():
        try:
            state['process']=await await_callback_result(start(controller.signal));process=state['process']
            try:
                if controller.signal.aborted:field(process,'kill')()
            finally:await asyncio.shield(field(process,'done'))
            return outcome(process)
        except Exception as error:
            killed=controller.signal.aborted and state['process'] is None
            if not killed:state['failure']=dict(error=error)
            return dict(status='killed' if killed else 'failed',detail=js_to_string(error.value) if isinstance(error,ThrownValueError) else str(error))
    done=CleanupPromise(start_coroutine(run()))
    def cancel(reason=None):
        if controller.signal.aborted:return
        controller.abort(reason)
        if state['process'] is not None:field(state['process'],'kill')()
    return NS(cancel=cancel,done=done,failure=lambda:state['failure'])
