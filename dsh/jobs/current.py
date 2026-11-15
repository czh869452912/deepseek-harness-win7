"""Current job registry: exact owner lifetimes, durable edges and output cursors."""
import asyncio
import math
import time
import uuid
from types import SimpleNamespace as NS

from dsh.cordis.awaiting import await_callback_result,start_coroutine
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.core.cancellation import aborted,subscribe_abort
from dsh.core.scope import ScopedLayers,scope_of
from dsh.core.session.json import UNDEFINED
from .error import JobError
from .events import JobLayer,JobEventHub
from .pump import start_pump,field
from .ring import OutputRing

DEFAULTS=dict(maxConcurrentJobsPerOwner=10,retainBytes=262144,settledRetainBytes=16384,pumpPollMs=150)


def terminal(job):return job['status'] in ('completed','killed','failed')


class JobWaitAborted(RuntimeError):
    name='AbortError'
    def __init__(self):super().__init__('wait aborted')


class CurrentLocalJobRegistry(Service):
    Config=Schema.object({key:Schema.number().default(value) for key,value in DEFAULTS.items()})

    def __init__(self,ctx,config=None):
        values=dict(DEFAULTS,**(config or {}))
        for key,value in values.items():
            if type(value) not in (int,float) or not 0<value<=9007199254740991 or int(value)!=value:
                raise ValueError(key+' must be a positive safe integer')
        super().__init__(ctx,'jobs');self.self_ctx=ctx;self.config_values=values
        self.store={};self.owner_cleanups={};self.tasks=set()
        self.layers=ScopedLayers(lambda _:JobLayer());self.hub=JobEventHub(self.layers,ctx.logger.warn)
        ctx.effect(lambda:self.dispose_all,'jobs teardown')

    @property
    def events(self):
        registrar=self.ctx
        return NS(subscribe=lambda filter,listener:self.hub.subscribe(registrar,filter,listener))

    def attachController(self,name):
        token=object()
        return self.layers.effect(self.ctx,lambda layer:layer.controllers.append(token),dict(label='jobs.attachController()'))

    def owner(self,identity):
        if identity is None:return None
        agents=self.self_ctx.get('agents')
        if agents is None:raise JobError('background job ownership requires the agent registry (load @deepseek-ai/dsh-agent)','JOB_OWNER_REGISTRY_UNAVAILABLE')
        owner=agents.get(identity)
        if owner is None:raise JobError('session "%s" has no live agent (background job owner must be live)' % identity,'JOB_OWNER_NOT_LIVE')
        return owner

    def track(self,operation):
        task=asyncio.ensure_future(operation);self.tasks.add(task)
        def done(future):
            self.tasks.discard(future)
            if not future.cancelled():future.exception()
        task.add_done_callback(done);return task

    def start(self,spec):
        owner=self.owner(spec.get('owner'));layers=[self.layers.global_layer]+self.layers.chain_layers(scope_of(owner.ctx) if owner is not None else None)
        if not any(not layer.controllers.is_empty() for layer in layers):
            raise JobError('background jobs unavailable: no job controller serves this agent (load @deepseek-ai/dsh-tool-jobs in its composition)','JOB_CONTROLLER_UNAVAILABLE')
        for key in ('kind','label'):
            if not spec[key]:raise ValueError('invalid job %s: expected a non-empty string' % key)
        limit=spec.get('outputLimitBytes')
        if limit is not None and (type(limit) not in (int,float) or not 0<limit<=9007199254740991 or int(limit)!=limit):
            raise ValueError('invalid outputLimitBytes: expected a positive safe integer, got '+stringify_json(limit))
        if owner is not None:self.ensure_owner_cleanup(owner)
        if sum(job['owner'] is owner and not terminal(job) for job in self.store.values())>=self.config_values['maxConcurrentJobsPerOwner']:
            raise JobError('background job limit reached for this owner (limit: %s); use job_kill to stop an unneeded job, wait for it to finish, then retry' % self.config_values['maxConcurrentJobsPerOwner'],'JOB_LIMIT_REACHED')
        identity=spec['kind']+'-'+uuid.uuid4().hex[:16]
        while identity in self.store:identity=spec['kind']+'-'+uuid.uuid4().hex[:16]
        ring=OutputRing();state=dict(job=None,progress=None)
        handle=NS(id=identity,append=lambda text,options=None:self.append_ring(state,ring,text,options,'producer'),updateProgress=lambda line:self.update_progress(state,line))
        hooks=spec['run'](handle)
        job=dict(id=identity,kind=spec['kind'],label=spec['label'],owner=owner,outputLimitBytes=limit,
            toolCall=dict(spec['toolCall']) if 'toolCall' in spec else None,ring=ring,state=state,cancel=field(hooks,'cancel'),
            status='running',modelCursor=0,resultDelivered=False,detail=None,result=UNDEFINED,startedAt=int(time.time()*1000),
            finishedAt=None,killReason=None,settleCause=None,settled=asyncio.get_running_loop().create_future(),waiters={},pump=None,spillPaths=[])
        state['job']=job;self.store[identity]=job;self.record(job);self.emit(dict(type='registered',job=self.view(job)),owner)
        async def producer():
            try:return dict(outcome=await field(hooks,'done'),reported=True)
            except Exception as error:
                self.self_ctx.logger.warn('jobs: job %s producer done promise rejected (producer contract violation): %s' % (identity,js_to_string(error)))
                return dict(outcome=dict(status='failed',detail=js_to_string(error)),reported=False)
        produced=self.track(producer())
        output=spec.get('output')
        if output:
            async def until():
                await asyncio.wait([produced,job['settled']],return_when=asyncio.FIRST_COMPLETED)
            def spill(index,path):
                while len(job['spillPaths'])<=index:job['spillPaths'].append(None)
                job['spillPaths'][index]=path
            job['pump']=start_pump([self.guard_source(job,source) for source in output],
                dict(append=lambda text,options=None:self.append_ring(state,ring,text,options,'pump'),spill=spill),self.config_values['pumpPollMs'],self.track(until()))
        async def finish():
            result=await asyncio.shield(produced)
            if job['pump'] is not None:await job['pump'].done
            self.settle(job,result['outcome'],job['settleCause'] or 'producer',result['reported'])
        self.track(finish());return identity

    def expect(self,identity,caller):
        job=self.store.get(identity)
        if job is None:raise JobError('unknown job '+identity,'JOB_NOT_FOUND')
        if job['owner'] is not None and job['owner'].id!=caller:raise JobError('job %s belongs to another session' % identity,'JOB_FOREIGN_SESSION')
        return job

    def view(self,job):
        value={key:job[key] for key in ('id','kind','label','outputLimitBytes','status','detail','startedAt','finishedAt') if job[key] is not None}
        if job['owner'] is not None:value['owner']=job['owner'].id
        if job['state']['progress'] is not None:value['progress']=job['state']['progress']
        ring=job['ring'];value['output']=dict(total=ring.total,earliest=ring.earliest)
        paths=list(dict.fromkeys(path for path in job['spillPaths'] if path is not None))
        if paths:value['output']['spillPaths']=paths
        return value

    def list(self,caller=None):return [self.view(job) for job in self.store.values() if job['owner'] is None or job['owner'].id==caller]
    def get(self,identity,caller=None):return self.view(self.expect(identity,caller))

    def readAt(self,identity,offset,caller=None):
        job=self.expect(identity,caller)
        if type(offset) not in (int,float) or not 0<=offset<=9007199254740991 or int(offset)!=offset:
            raise ValueError('invalid output read offset: expected a non-negative safe integer, got '+stringify_json(offset))
        return job['ring'].readFrom(offset)

    def read(self,identity,caller=None):
        job=self.expect(identity,caller);ring=job['ring'];read=ring.readFrom(job['modelCursor']);job['modelCursor']=ring.total
        result=job['result'] if terminal(job) and not job['resultDelivered'] else UNDEFINED
        if result is not UNDEFINED:job['resultDelivered']=True
        if terminal(job):ring.trim(self.config_values['settledRetainBytes'])
        return dict(chunks=read['chunks'],lossy=read['lossy'],job=self.view(job),**({} if result is UNDEFINED else dict(result=result)))

    def kill(self,identity,caller=None,reason=None):
        job=self.expect(identity,caller)
        if terminal(job):return 'already-finished'
        job['cancel'](reason);job['status']='stopping'
        if reason is not None:job['killReason']=reason
        job['settleCause']='kill';self.emit(dict(type='stopping',job=self.view(job)),job['owner']);return 'requested'

    async def wait(self,identity,timeout_ms,caller=None,signal=None):
        job=self.expect(identity,caller)
        if type(timeout_ms) not in (int,float) or not 0<timeout_ms or not math.isfinite(timeout_ms):
            raise ValueError('invalid wait timeout: expected a positive number of milliseconds, got '+stringify_json(timeout_ms))
        if not terminal(job):
            if aborted(signal):raise JobWaitAborted()
            result=asyncio.get_running_loop().create_future();token=object();detach=lambda:None
            def finish(error=None):
                job['waiters'].pop(token,None);detach()
                if not result.done():
                    if error is None:result.set_result(None)
                    else:result.set_exception(error)
            job['waiters'][token]=finish
            detach=subscribe_abort(signal,lambda _:finish(JobWaitAborted()))
            timer=asyncio.get_running_loop().call_later(timeout_ms/1000,finish)
            try:await result
            finally:job['waiters'].pop(token,None);detach();timer.cancel()
        return self.view(job)

    def remove(self,identity,caller=None):
        job=self.expect(identity,caller)
        if not terminal(job):raise RuntimeError('job %s is still %s; kill it and wait for settlement before removing it' % (identity,job['status']))
        self.drop([job])

    def emit(self,event,owner):self.hub.emit(event,owner)

    def record(self,job,settlement=None):
        owner=job['owner']
        if owner is None:return
        data=dict(jobId=job['id'],owner=owner.id,kind=job['kind'],label=job['label'],startedAt=job['startedAt'])
        if job['toolCall'] is not None:data['toolCall']=job['toolCall']
        try:
            if settlement is None:owner.session.append('job/registered',data)
            else:owner.session.append('job/settled',dict(data,**settlement))
        except Exception as error:self.self_ctx.logger.warn('jobs: failed to record lifecycle for %s: %s' % (job['id'],error))

    def append_ring(self,state,ring,text,options,writer):
        job=state['job']
        if job is not None and terminal(job):
            if writer=='producer':self.self_ctx.logger.warn('jobs: append to settled job %s dropped' % job['id'])
            return
        if ring.append(text,options,self.config_values['retainBytes']) and job is not None:self.emit_output(job)

    def update_progress(self,state,line):
        job=state['job']
        if job is not None and terminal(job):
            self.self_ctx.logger.warn('jobs: progress update on settled job %s dropped' % job['id']);return
        state['progress']=line
        if job is not None:self.emit(dict(type='progress',job=self.view(job)),job['owner'])

    def guard_source(self,job,source):
        failed=False
        def read(offset):
            nonlocal failed
            if not failed:
                try:return field(source,'read')(offset)
                except Exception as error:
                    failed=True;self.self_ctx.logger.warn('jobs: output source for %s failed; its stream stops here: %s' % (job['id'],error))
            return dict(text='',nextOffset=offset,lossy=False)
        return dict(read=read,**({} if field(source,'channel') is None else dict(channel=field(source,'channel'))))

    def emit_output(self,job):
        self.emit(dict(type='output',id=job['id'],total=job['ring'].total,**({} if job['owner'] is None else dict(owner=job['owner'].id))),job['owner'])

    def settle(self,job,outcome,cause,reported):
        if terminal(job):return
        job['status']=outcome['status']
        if outcome['status']=='killed' and job['killReason'] is not None:
            job['detail']=(outcome['detail']+'; ' if 'detail' in outcome else '')+job['killReason']
        elif 'detail' in outcome:job['detail']=outcome['detail']
        job['state']['progress']=None;job['result']=outcome.get('result',UNDEFINED);job['finishedAt']=int(time.time()*1000)
        self.record(job,dict(finishedAt=job['finishedAt'],status=outcome['status'],cause=cause,producerReported=reported,**({} if job['detail'] is None else dict(detail=job['detail']))))
        job['ring'].trim(max(self.config_values['settledRetainBytes'],job['ring'].total-job['modelCursor']))
        waiters=list(job['waiters'].values());job['waiters'].clear()
        for finish in waiters:finish()
        job['settled'].set_result(None)
        self.emit(dict(type='settled',job=self.view(job),cause=cause,awaited=bool(waiters)),job['owner']);self.emit_output(job)

    def ensure_owner_cleanup(self,owner):
        if owner in self.owner_cleanups:return
        async def cleanup():
            self.owner_cleanups.pop(owner,None)
            jobs=[job for job in self.store.values() if job['owner'] is owner]
            await self.retire(jobs,'owner disposed');self.drop(jobs)
        self.owner_cleanups[owner]=owner.ctx.effect(lambda:cleanup,'jobs.ownerCleanup()')

    def drop(self,jobs):
        for job in jobs:
            self.store.pop(job['id'],None);self.emit(dict(type='removed',job=self.view(job)),job['owner'])

    async def retire(self,jobs,reason):
        for job in jobs:
            if terminal(job):continue
            job['settleCause']='teardown'
            try:
                job['cancel'](reason);job['status']='stopping';self.emit(dict(type='stopping',job=self.view(job)),job['owner'])
            except Exception as error:
                detail='cancel threw during teardown; work may be orphaned: '+js_to_string(error)
                self.self_ctx.logger.warn('jobs: cancel of %s threw during teardown; job record forced failed and work may be orphaned: %s' % (job['id'],error))
                self.settle(job,dict(status='failed',detail=detail),'teardown',False)
        await asyncio.gather(*(asyncio.shield(job['settled']) for job in jobs))
        await asyncio.gather(*(job['pump'].done for job in jobs if job['pump'] is not None))

    async def dispose_all(self):
        jobs=list(self.store.values());await self.retire(jobs,'jobs service disposed');self.drop(jobs)
        cleanups=list(self.owner_cleanups.values());self.owner_cleanups.clear()
        await asyncio.gather(*(await_callback_result(cleanup()) for cleanup in cleanups))
