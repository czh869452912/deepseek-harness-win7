"""Shell job bridge preparation/abort ownership and PowerShell output markers."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.shell.jobs_current import process_job,process_outcome,process_sources,ring_delta
    from dsh.shell.render_current import render_result,render_promoted,render_job_read
    from dsh.cordis.errors import ThrownValueError
    rows=[]
    for status,code,signal,sandbox in [('completed',0,None,None),('completed',5,None,None),('killed',None,None,None),('killed',None,'SIGTERM',None),('completed',1,None,dict(mode='read-only',denied=True)),('completed',1,None,dict(mode='read-only',denied=True,runnerFailed=True))]:
        process=NS(status=status,exitCode=code,signal=signal,sandbox=sandbox)
        rows.append(dict(name='outcome',value=process_outcome(process,['workspace-write'])))
    for options in ({},{'timedOut':True,'exitCode':0},{'stopped':'human','exitCode':1},{'signal':'SIGINT','exitCode':None},{'sandbox':dict(mode='read-only',denied=True)}):
        result=dict(exitCode=3,signal=None,timedOut=False,timeoutMs=10,stdout=dict(text='out',truncated=True,spillPath='C:/out'),stderr=dict(text='err',truncated=True),**{})
        result.update(options);rows.append(dict(name='foreground-render',text=render_result(result,['workspace-write'])))
    for text in ('','out','out\n'):
        rows.append(dict(name='promoted',text=render_promoted(dict(jobId='job',timeoutMs=10,output=text))))
    for sandbox in (None,dict(mode='read-only',denied=True),dict(mode='workspace-write',denied=False,runnerFailed=True)):
        rows.append(dict(name='job-read',text=render_job_read('out',True,['a','b'],sandbox,['danger-full-access'])))
    chunks=[dict(text='out'),dict(text='log',channel='log'),dict(text='err',channel='stderr')];rows.append(dict(name='delta',text=ring_delta(chunks)))
    current=[None];sources=process_sources(lambda:current[0]);before=[source['read'](3) for source in sources]
    current[0]=NS(observed=NS(**{channel:NS(readFrom=lambda offset,channel=channel:dict(text=channel,nextOffset=offset+6,lossy=True,spillPath=channel)) for channel in ('stdout','stderr')}))
    rows.append(dict(name='sources',channels=[source['channel'] for source in sources],before=before,after=[source['read'](3) for source in sources]))
    async def drain():
        for _ in range(6):await asyncio.sleep(0)
    for when in ('preparation','running'):
        gate=asyncio.get_running_loop().create_future();finished=asyncio.get_running_loop().create_future();trace=[];seen=[]
        process=NS(status='running',exitCode=None,signal=None,sandbox=None,done=finished)
        def kill():trace.append('kill');process.status='killed';finished.set_result(None)
        process.kill=kill
        async def start(signal):seen.append(signal);trace.append('start');await gate;trace.append('prepared');return process
        hooks=process_job(start,process_outcome)
        if when=='running':gate.set_result(None);await drain()
        hooks.cancel('stop');hooks.cancel('again')
        if when=='preparation':gate.set_result(None)
        result=await hooks.done;rows.append(dict(name=when,trace=trace,result=result,aborted=seen[0].aborted,reason=seen[0].reason,failure=hooks.failure()))
    for kind in ('prepare','cancel-prepare','process','thrown-value'):
        gate=asyncio.get_running_loop().create_future();original=ThrownValueError(0) if kind=='thrown-value' else RuntimeError('original failure')
        async def start(signal):return await gate
        hooks=process_job(start,process_outcome)
        if kind=='cancel-prepare':hooks.cancel('stop')
        if kind=='process':
            finished=asyncio.get_running_loop().create_future();gate.set_result(NS(done=finished,kill=lambda:None));await drain();finished.set_exception(original)
        else:gate.set_exception(original)
        result=await hooks.done;failure=hooks.failure();rows.append(dict(name=kind,result=result,originalError=failure is not None and failure['error'] is original))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_shell_job.mts','Source PowerShell background bridge and render helpers: exit-versus-infrastructure vocabulary, sandbox marker ordering, output/promoted markers, non-consuming delayed readers, preparation and live cancellation ownership, idempotence and boxed original failures including non-Error thrown values.',[Path(__file__).resolve(),ROOT/'dsh/shell/jobs_current.py',ROOT/'dsh/shell/render_current.py'])
