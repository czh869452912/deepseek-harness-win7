"""Current job Remote callbacks against actual Source observation generators."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    rows=[dict(name='empty',texts=[]),dict(name='batch',texts=['ab','🐱','tail'],budget=5),dict(name='oversized',texts=['long 🐱 chunk'],budget=2),dict(name='resume',texts=['ab','🐱','tail'],offset=3),dict(name='future',texts=['one'],offset=99),dict(name='evicted',texts=['older','last'],cap=4,offset=0),dict(name='loss-only',texts=['🐱'],cap=1,offset=0)]
    rows += [dict(name='offset-'+str(i),offset=value) for i,value in enumerate((-1,0.5,True,None,9007199254740992))]
    rows += [dict(name=name) for name in ('missing','foreign','aborted','removed','live','rows','unowned','kill-running','kill-finished','kill-missing','kill-foreign','kill-cancel-failed','kill-lookup-text','kill-lookup-error')]
    rows.append(dict(name='loss-empty'))
    return rows


class Registry:
    def __init__(self,case):
        from dsh.jobs.ring import OutputRing
        self.case=case;self.ring=OutputRing();self.listeners=[];self.calls=[];self.status='running' if case['name'] in ('live','removed','kill-running','kill-cancel-failed') else 'completed';self.deleted=False;self.error=RuntimeError('producer cancel failed')
        self.events=NS(subscribe=self.subscribe)
        for text in case.get('texts',[]):self.ring.append(text,dict(channel='stdout'),case.get('cap',65536))
    def subscribe(self,filter,listener):
        self.calls.append(dict(subscribe=filter));self.listeners.append(listener)
        def dispose():self.calls.append('unsubscribe');self.listeners.remove(listener)
        return dispose
    def emit(self,event):
        for listener in list(self.listeners):listener(event)
    def view(self):return dict(id='job',**({} if self.case['name']=='unowned' else dict(owner='owner')),status=self.status,kind='bash',label='work',startedAt=1,output=dict(earliest=self.ring.earliest,total=self.ring.total))
    def get(self,identity,caller=None):
        from dsh.jobs.error import JobError
        from dsh.cordis.errors import ThrownValueError
        self.calls.append(dict(get=[identity,caller]))
        if self.case['name']=='kill-lookup-text':raise ThrownValueError('lookup unavailable')
        if self.case['name']=='kill-lookup-error':raise RuntimeError('lookup unavailable')
        if self.deleted or self.case['name'] in ('missing','kill-missing'):raise JobError('unknown job '+identity,'JOB_NOT_FOUND')
        if self.case['name'] in ('foreign','kill-foreign'):raise JobError('job '+identity+' belongs to another session','JOB_FOREIGN_SESSION')
        return self.view()
    def readAt(self,identity,offset,caller=None):
        self.calls.append(dict(readAt=[identity,offset,caller]))
        return dict(chunks=[],next=0,lossy=True) if self.case['name']=='loss-empty' else self.ring.readFrom(offset)
    def list(self,caller):self.calls.append(dict(list=caller));return [self.view()]
    def kill(self,identity,caller,reason):
        self.calls.append(dict(kill=[identity,caller,reason]))
        if self.case['name']=='kill-cancel-failed':raise self.error
        return 'already-finished' if self.status=='completed' else 'requested'


async def observe():
    from dsh.core.abort import AbortController
    from dsh.jobs.controller_current import CurrentJobController
    rows=[]
    for case in corpus():
        registry=Registry(case);controller=CurrentJobController.__new__(CurrentJobController);controller.ctx=NS(jobs=registry);controller.flush_ms=1;controller.max_frame_bytes=case.get('budget',65536)
        abort=AbortController();reason=RuntimeError('carrier stopped');name=case['name'];frames=[];early=None;result=None
        if name=='aborted':abort.abort(reason)
        request=dict(jobId='job',sessionId='owner')
        if name=='unowned':request.pop('sessionId')
        if 'offset' in case:request['from']=case['offset']
        stream=None
        try:
            if name.startswith('kill-'):result=controller.kill(request)
            elif name=='rows':
                stream=controller.list(dict(sessionId='owner'),abort.signal);frames.append(await stream.__anext__())
                pending=asyncio.ensure_future(stream.__anext__());await asyncio.sleep(0)
                registry.emit(dict(type='output',id='job'));registry.emit(dict(type='progress',job=dict(id='foreign',owner='other')));await asyncio.sleep(0);early=pending.done()
                registry.emit(dict(type='progress',job=registry.view()));frames.append(await pending)
                pending=asyncio.ensure_future(stream.__anext__());await asyncio.sleep(0);abort.abort(reason)
                try:await pending
                except StopAsyncIteration:pass
            elif name in ('removed','live'):
                stream=controller.follow(request,abort.signal);frames.append(await stream.__anext__())
                if name=='removed':
                    registry.status='killed';registry.deleted=True;registry.emit(dict(type='removed',job=registry.view()));frames.append(await stream.__anext__())
                else:
                    pending=asyncio.ensure_future(stream.__anext__());await asyncio.sleep(0)
                    registry.ring.append('live 🐱',dict(channel='stderr'),65536);registry.emit(dict(type='output',id='job'));frames.append(await pending)
                    registry.status='completed';registry.emit(dict(type='settled',job=registry.view()));frames.append(await stream.__anext__())
                async for frame in stream:frames.append(frame)
            else:
                stream=controller.follow(request,abort.signal)
                async for frame in stream:frames.append(frame)
        except Exception as error:
            result=dict(error=dict(name=getattr(error,'name','Error'),message=getattr(error,'message',str(error)),code=getattr(error,'code',None),details=getattr(error,'details',None),original=error is registry.error or error is reason))
        finally:
            if stream is not None:await stream.aclose()
        rows.append(dict(name=name,frames=frames,result=result,early=early,calls=registry.calls,listeners=len(registry.listeners)))
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_job_controller.mts','Actual job observation and controller callbacks: byte-resume/lossy frames, bounded batches/whole large chunks, removed/live jobs, roster owner/output filtering, cancellation/unsubscribe, human kill errors and producer cancel identity; no consuming registry read invoked.',[Path(__file__).resolve(),ROOT/'dsh/jobs/observe_current.py',ROOT/'dsh/jobs/controller_current.py'],prepare=prepare)
