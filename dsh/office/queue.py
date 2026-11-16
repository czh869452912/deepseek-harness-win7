"""Metadata-first source admission and converter-generation content reuse."""
import asyncio
import hashlib

from dsh.cordis.awaiting import await_callback_result,start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.typert.stores import field
from .errors import OfficeKitError

DEFAULTS=dict(maxConcurrentConversions=2,maxQueuedJobs=8,maxReaders=32,maxSourceBytes=104857600,
    maxBackgroundConversions=1,maxCachedEntries=8,maxCachedBytes=134217728,maxSourceEntries=64,maxInputBytes=52428800)


class Record:
    def __init__(self,**values):self.__dict__.update(values)


class _CancelledReason:
    def __init__(self,error):self.error=error


class ReadPromise(CleanupPromise):
    """Carry a CancelledError rejection without converting it to Task.cancel()."""
    def __init__(self,promise):
        async def capture():
            try:return await asyncio.shield(promise)
            except asyncio.CancelledError as error:return _CancelledReason(error)
        super().__init__(capture())

    def __await__(self):
        async def wait():
            value=await asyncio.shield(self.task)
            if isinstance(value,_CancelledReason):raise value.error
            return value
        return wait().__await__()


def output_bytes(output):
    kind=output['kind']
    if kind=='pdf':return len(output['pdf'])
    if kind=='file':return len(output['data'])
    if kind=='images':return sum(len(image['png']) for image in output['images'])
    raise RuntimeError('Unexpected Office output: '+stringify_json(output))


def copy_output(result):
    copied=dict(result,missingFonts=list(result['missingFonts']));kind=result['kind']
    if kind=='pdf':copied['pdf']=bytearray(result['pdf'])
    elif kind=='file':copied['data']=bytearray(result['data'])
    elif kind=='images':copied['images']=[dict(image,png=bytearray(image['png'])) for image in result['images']]
    else:raise RuntimeError('Unexpected Office output: '+stringify_json(result))
    return copied


class ConversionQueue:
    def __init__(self,config,generation,convert):
        self.config=dict(DEFAULTS,**config);self.generation=generation;self.convert=convert
        self.ready={};self.aliases={};self.sources={};self.digests={};self.queue=[];self.tasks={};self.jobs={}
        self.cachedBytes=0;self.sourceBytes=0;self.running=0;self.background=0;self.readers=0;self.disposed=False

    @staticmethod
    def busy():return OfficeKitError('busy','The document converter has reached its admission limit.')
    @staticmethod
    def unavailable():return OfficeKitError('unavailable','The document converter is unavailable.')

    def read(self,request,signal=None):
        promise=asyncio.get_running_loop().create_future()
        # Admission happens before returning, like the Source async entry prefix.
        try:self._admit(request,signal,promise)
        except (Exception,asyncio.CancelledError) as error:promise.set_exception(error)
        return ReadPromise(promise)

    def _admit(self,request,signal,promise):
        if signal is not None:signal.throwIfAborted()
        if self.disposed:raise self.unavailable()
        source_request=request['source'];size=field(source_request,'bytes')
        if size is not None and size>self.config['maxInputBytes']:raise OfficeKitError('input-too-large','The Office source exceeds maxInputBytes.')
        operation=stringify_json(request['operation']);source=stringify_json([field(source_request,'key'),field(source_request,'version'),request['extension'],operation])
        alias=self.aliases.get(source);cached=self.ready.get(alias)
        if cached is not None:
            self.ready.pop(cached['cacheKey']);self.ready[cached['cacheKey']]=cached;self.aliases.pop(source);self.aliases[source]=cached['cacheKey']
            promise.set_result(copy_output(cached));return
        priority=request['priority'];limit=self.config['maxReaders']-(1 if priority=='background' else 0)
        if self.readers>=limit or priority=='background' and self.config['maxBackgroundConversions']==0:raise self.busy()
        job=self.sources.get(source)
        if job is None:
            if len(self.queue)>=self.config['maxQueuedJobs']:
                obsolete=next((item for item in self.queue if item.priority=='background'),None) if priority=='foreground' else None
                if obsolete is None:raise self.busy()
                self.fail(obsolete,self.busy())
            job=Record(request=request,operation=operation,priority=priority,controller=AbortController(),readers={},sources={source:None},state='queued')
            self.sources[source]=job;self.jobs[job]=None;self.queue.append(job)
        if priority=='foreground':job.priority='foreground'
        self.readers+=1
        reader=Record(job=job,source=source,priority=priority,promise=promise,cleanup=lambda:None)
        def abort(_):
            self.release(reader);reason=signal.reason
            if isinstance(reason,BaseException):error=reason
            else:error=RuntimeError('Office conversion cancelled');error.cause=reason
            if not promise.done():promise.set_exception(error)
            if not reader.job.readers:self.cancel(reader.job)
            self.drain()
        job.readers[reader]=None
        if signal is not None:
            signal.addEventListener('abort',abort)
            reader.cleanup=lambda:signal.removeEventListener('abort',abort)
        self.drain()

    def dispose(self):
        async def finish():
            self.disposed=True
            for job in tuple(self.jobs):self.fail(job,self.unavailable())
            self.ready.clear();self.aliases.clear();self.cachedBytes=0
            await asyncio.gather(*tuple(self.tasks),return_exceptions=True)
        return CleanupPromise(start_coroutine(finish()))

    def release(self,reader):
        job=reader.job;job.readers.pop(reader,None)
        if job.state=='queued':job.priority='foreground' if any(item.priority=='foreground' for item in job.readers) else 'background'
        if not any(item.source==reader.source for item in job.readers):
            job.sources.pop(reader.source,None)
            if self.sources.get(reader.source) is job:self.sources.pop(reader.source)
        reader.cleanup();self.readers-=1

    def cancel(self,job):
        job.controller.abort()
        if job.state=='queued':self.queue.remove(job);job.state='finished';self.jobs.pop(job,None)

    def fail(self,job,error):
        for reader in tuple(job.readers):
            self.release(reader)
            if not reader.promise.done():reader.promise.set_exception(error)
        self.cancel(job)

    def reservation(self,job):
        size=field(job.request['source'],'bytes');return max(1,self.config['maxInputBytes'] if size is None else size)

    def drain(self):
        while not self.disposed and self.running<self.config['maxConcurrentConversions']:
            def eligible(job):
                return self.sourceBytes+self.reservation(job)<=self.config['maxSourceBytes'] and (job.priority=='foreground' or self.background<min(self.config['maxBackgroundConversions'],max(1,self.config['maxConcurrentConversions']-1)))
            foreground_waiting=any(item.priority=='foreground' for item in self.queue)
            job=next((item for item in self.queue if (not foreground_waiting or item.priority=='foreground') and eligible(item)),None)
            if job is None:return
            self.queue.remove(job);job.state='running';background=job.priority=='background';reserved=self.reservation(job)
            self.running+=1;self.background+=int(background);self.sourceBytes+=reserved
            self._start(job,reserved,background)

    def _start(self,job,reserved,background):
        async def execute():
            try:await await_callback_result(self.execute(job,reserved))
            except (Exception,asyncio.CancelledError) as error:self.fail(job,error)
            finally:
                self.running-=1;self.background-=int(background);self.sourceBytes-=reserved;job.state='finished';self.jobs.pop(job,None);self.tasks.pop(task,None);self.drain()
        task=start_coroutine(execute());self.tasks[task]=None
        task.add_done_callback(lambda done:None if done.cancelled() else done.exception())

    async def execute(self,job,reserved):
        signal=job.controller.signal;signal.throwIfAborted();source=job.request['source']
        value=await await_callback_result(field(source,'read')(signal,reserved));signal.throwIfAborted()
        if field(value,'version')!=field(source,'version'):raise OfficeKitError('source-changed','The source changed while waiting for conversion.')
        data=field(value,'bytes')
        if len(data)>reserved:raise OfficeKitError('input-too-large','The source exceeds its reserved read capacity.')
        digest=hashlib.sha256(job.request['extension'].encode('utf-8')+b'\0'+job.operation.encode('utf-8')+b'\0'+bytes(data)).hexdigest();key=self.generation+':'+digest
        cached=self.ready.get(key)
        if cached is not None:self.ready.pop(key);self.ready[key]=cached;self.finish(job,cached);return
        existing=self.digests.get(key)
        if existing is not None and not existing.controller.signal.aborted:
            if job.priority=='foreground':existing.priority='foreground'
            for reader in job.readers:reader.job=existing;existing.readers[reader]=None
            job.readers.clear()
            for source_key in job.sources:existing.sources[source_key]=None;self.sources[source_key]=existing
            job.sources.clear();return
        self.digests[key]=job
        try:
            converted=await await_callback_result(self.convert(data,job.request,signal));signal.throwIfAborted()
            result=dict(converted,cacheKey=key,generation=self.generation);self.retain(result);self.finish(job,result)
        finally:
            if self.digests.get(key) is job:self.digests.pop(key)

    def finish(self,job,result):
        for source in job.sources:self.sources.pop(source,None)
        if result['cacheKey'] in self.ready:
            for source in job.sources:
                self.aliases.pop(source,None);self.aliases[source]=result['cacheKey']
                while len(self.aliases)>self.config['maxSourceEntries']:self.aliases.pop(next(iter(self.aliases)))
        for reader in tuple(job.readers):
            self.release(reader)
            if not reader.promise.done():reader.promise.set_result(copy_output(result))

    def retain(self,result):
        size=output_bytes(result)
        if size>self.config['maxCachedBytes']:return
        while len(self.ready)>=self.config['maxCachedEntries'] or self.cachedBytes+size>self.config['maxCachedBytes']:
            key=next(iter(self.ready));oldest=self.ready.pop(key);self.cachedBytes-=output_bytes(oldest)
            for source,digest in tuple(self.aliases.items()):
                if digest==key:self.aliases.pop(source)
        self.ready[result['cacheKey']]=result;self.cachedBytes+=size
