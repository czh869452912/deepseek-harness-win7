"""Shared Office operations, authorized previews and optional native engine service."""
import asyncio
import os
import tempfile
import uuid
from types import SimpleNamespace

from dsh.cordis.awaiting import await_callback_result,start_coroutine
from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.errors import AggregateError
from dsh.cordis.json_text import stringify_json
from dsh.cordis.schema import Schema as z
from dsh.cordis.text import lower_js
from dsh.cordis.utils import _UNDEFINED
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.typert.remote import Remote,RemoteError,TypertRemoteService
from dsh.typert.stores import field
from .errors import OfficeKitError
from .output import read_output,read_pdf,read_png
from .outputs import OutputStore,_io,_remove_tree,_native
from .queue import ConversionQueue,DEFAULTS as QUEUE_DEFAULTS

DEFAULTS=dict(QUEUE_DEFAULTS,outputRetentionMs=86400000,maxOutputStoreBytes=536870912,timeoutMs=60000,
    maxOutputBytes=104857600,maxImageResolution=192,maxArchiveEntries=10000,maxUncompressedBytes=262144000,
    maxFontFiles=20000,maxFontFileBytes=268435456,maxLoadedFontBytes=536870912)
TIMER_KEYS=('outputRetentionMs','timeoutMs','maxImageResolution')
OPTION_KEYS=('fontDirectories','fontFallbacks','timeoutMs','maxInputBytes','maxOutputBytes','maxImageResolution',
    'maxArchiveEntries','maxUncompressedBytes','maxFontFiles','maxFontFileBytes','maxLoadedFontBytes')
KIT_HINT='This deployment does not provide LibreOffice Kit; install or enable it as this deployment requires, then retry.'


def config_schema():
    entries={key:z.natural().min(0 if key=='maxBackgroundConversions' else 1).max(2147483647 if key in TIMER_KEYS else 9007199254740990 if key in ('maxInputBytes','maxOutputBytes') else 9007199254740991).default(value) for key,value in DEFAULTS.items()}
    entries['outputDirectory']=z.string().min(1).default(os.path.join(resolve_dsh_home(),'office-kit','outputs'))
    entries['fontDirectories']=z.array(z.string().min(1)).extra('default',_UNDEFINED)
    entries['fontFallbacks']=z.array(z.array(z.string().pattern(r'[^\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]')).min(2)).extra('default',_UNDEFINED)
    return z.object(entries)


class CurrentOfficeKit(TypertRemoteService):
    Config=config_schema()

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'officeKit');self.config=dict(DEFAULTS,**(config or {}));self.config.setdefault('outputDirectory',os.path.join(resolve_dsh_home(),'office-kit','outputs'))
        for key in ('fontDirectories','fontFallbacks'):
            if self.config.get(key) is _UNDEFINED:self.config.pop(key,None)
        if any(not os.path.isabs(path) for path in self.config.get('fontDirectories',[])):raise ValueError('fontDirectories must contain absolute paths.')
        if self.config['maxSourceBytes']<self.config['maxInputBytes']:raise ValueError('maxSourceBytes must be at least maxInputBytes.')
        if not os.path.isabs(self.config['outputDirectory']):raise ValueError('outputDirectory must be an absolute path.')
        self.generation=str(uuid.uuid4());self.outputDirectory=self.config['outputDirectory'];self.remoteLifetime=AbortController();self.remoteRequests={};self.slots=[];self.reported=set();self.loadedKit=None
        self.options={key:self.config[key] for key in OPTION_KEYS if key in self.config}
        self.queue=ConversionQueue(self.config,self.generation,self.runOperation)
        self.outputs=OutputStore(dict(root=self.outputDirectory,retentionMs=self.config['outputRetentionMs'],maxBytes=self.config['maxOutputStoreBytes']),ctx.logger.warn)
        ctx.on('session/disposed',lambda session:self.outputs.release(field(session,'id')))
        ctx.effect(lambda:self.close)

    async def close(self):
        self.remoteLifetime.abort();await self.queue.dispose();await self.outputs.dispose()
        await asyncio.gather(*tuple(self.remoteRequests),return_exceptions=True)
        async def close_slot(slot):
            converter=await slot.converter if slot.converter is not None else None
            if converter is not None:await await_callback_result(field(converter,'dispose')())
        results=await asyncio.gather(*(close_slot(slot) for slot in self.slots),return_exceptions=True)
        failures=[value for value in results if isinstance(value,BaseException)]
        if failures:raise AggregateError(failures,'LibreOffice converter disposal failed.')

    def convert(self,request,signal=None):
        async def convert():
            result=dict(await self.queue.read(dict(request,operation=dict(kind='pdf')),signal));result.pop('kind');return result
        return CleanupPromise(start_coroutine(convert()))

    def renderImages(self,request,signal=None):
        async def render():
            operation=dict(kind='images')
            for key in ('pages','sheet','range','dpi','maxImages','maxPixels','maxDimension','maxBytes'):
                if key in request:operation[key]=list(request[key]) if key=='pages' else request[key]
            result=await self.queue.read(dict(extension=request['extension'],source=request['source'],priority='foreground',operation=operation),signal)
            return {key:result[key] for key in ('images','pageCount','dpi','missingFonts')}
        return CleanupPromise(start_coroutine(render()))

    def convertTo(self,request,signal=None):return self.file_operation(request,'convert',signal)
    def recalculate(self,request,signal=None):return self.file_operation(request,'recalculate',signal)

    def file_operation(self,request,kind,signal):
        async def run():
            operation=dict(kind=kind,format=request['format'])
            if kind=='convert' and 'sheet' in request:operation['sheet']=request['sheet']
            result=await self.queue.read(dict(extension=request['extension'],source=request['source'],priority='foreground',operation=operation),signal)
            if signal is not None:signal.throwIfAborted()
            target=request['output'];path=await self.outputs.save(target['owner'],target['name'],result['data'])
            value=dict(path=path,bytes=len(result['data']),missingFonts=result['missingFonts'])
            if 'pageCount' in result:value['pageCount']=result['pageCount']
            return value
        return CleanupPromise(start_coroutine(run()))

    @Remote('generation')
    def getGeneration(self,signal):signal.throwIfAborted();return self.generation

    @Remote
    def render(self,workspaceFileScope,path,priority,signal):
        combined=AbortController();detach=[source.add_listener('abort',lambda reason:combined.abort(reason)) for source in (signal,self.remoteLifetime.signal)]
        async def run():
            try:return await self.renderFile(workspaceFileScope,path,priority,combined.signal)
            finally:
                for remove in detach:remove()
                self.remoteRequests.pop(operation,None)
        operation=CleanupPromise(run());self.remoteRequests[operation]=None;return operation

    async def renderFile(self,scope,path,priority,signal):
        try:
            signal.throwIfAborted();extension=lower_js(os.path.splitext(path)[1][1:])
            if extension not in ('doc','docx','xls','xlsx','ppt','pptx'):raise OfficeKitError('unsupported-format','The path must end in doc, docx, xls, xlsx, ppt, or pptx.')
            files=self.ctx.get('workspaceFiles');fs=self.ctx.get('fs')
            if files is None or fs is None:raise OfficeKitError('unavailable','Office file rendering requires workspaceFiles and fs.')
            authorized=await files.readBytes(scope,path,dict(range=dict(offset=0,length=1)),signal);source=await files.stat(scope,path,signal)
            def unchanged(current):
                if current['absolutePath']!=source['absolutePath'] or current['version']!=source['version']:raise OfficeKitError('source-changed','The source changed.')
            unchanged(authorized);signal.throwIfAborted()
            async def read(upstream,max_bytes):
                target=await fs.resolve(source['absolutePath'],dict(signal=upstream));info=await fs.stat(target,upstream)
                if info is None or field(info,'type')!='file':raise OfficeKitError('source-changed','The source changed.')
                unchanged(dict(absolutePath=fs.processPath(target),version=field(info,'version')))
                try:data=await fs.readBytes(target,upstream,max_bytes)
                except Exception as cause:
                    if getattr(cause,'code',None)=='FS_TOO_LARGE':
                        unchanged(await files.stat(scope,path,upstream));raise OfficeKitError('input-too-large','The source exceeds the reserved byte capacity.',cause=cause) from None
                    raise
                upstream.throwIfAborted();unchanged(await files.stat(scope,path,upstream));return dict(bytes=data,version=source['version'])
            metadata=dict(key=stringify_json([field(scope,'sessionId'),field(scope,'workspaceRoot'),source['absolutePath']]),version=source['version'],read=read)
            if 'bytes' in source:metadata['bytes']=source['bytes']
            result=await self.convert(dict(extension=extension,priority=priority,source=metadata),signal);signal.throwIfAborted()
            return dict(absolutePath=source['absolutePath'],version=source['version'],offset=0,eof=True,bytes=len(result['pdf']),data=result['pdf'],missingFonts=result['missingFonts'],generation=result['generation'])
        except (Exception,asyncio.CancelledError) as cause:
            if signal.aborted:raise RemoteError('gateway/cancelled','The document preview was cancelled.',{},cause=cause) from None
            if isinstance(cause,OfficeKitError):raise RemoteError('document-render/failed','Office conversion failed.',dict(reason=cause.code),cause=cause) from None
            raise

    def loadKit(self):
        if self.loadedKit is None:
            async def load():
                engine=self.ctx.get('officeKitEngine')
                if engine is None:
                    message='LibreOffice Kit is not installed. '+KIT_HINT
                    if message not in self.reported:self.reported.add(message);self.ctx.logger.warn(message)
                    raise OfficeKitError('unavailable',message)
                return engine
            loading=CleanupPromise(load());self.loadedKit=loading
            def release(done):
                if done.cancelled() or done.exception() is not None:self.loadedKit=None
            loading.add_done_callback(release)
        return self.loadedKit

    async def runOperation(self,data,request,signal):
        signal.throwIfAborted();slot=next((slot for slot in self.slots if not slot.busy),None)
        if slot is None:slot=SimpleNamespace(busy=False,converter=None);self.slots.append(slot)
        slot.busy=True;directory=None
        try:
            if slot.converter is None:
                async def create():
                    engine=await self.loadKit();return await await_callback_result(field(engine,'createConverter')(dict(self.options)))
                loading=CleanupPromise(create());slot.converter=loading
                def reset(done):
                    if done.cancelled() or done.exception() is not None:slot.converter=None
                loading.add_done_callback(reset)
            converter=await slot.converter;signal.throwIfAborted()
            directory=await _io(lambda:tempfile.mkdtemp(prefix='dsh-office-kit-'));input_path=os.path.join(directory,'source.'+request['extension'])
            def write():
                descriptor=os.open(_native(input_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
                try:
                    with os.fdopen(descriptor,'wb') as stream:descriptor=None;stream.write(data)
                finally:
                    if descriptor is not None:os.close(descriptor)
            await _io(write);signal.throwIfAborted();result=await self.runEngine(converter,input_path,directory,request['operation'],signal);signal.throwIfAborted();return result
        except (Exception,asyncio.CancelledError) as cause:
            signal.throwIfAborted()
            if isinstance(cause,OfficeKitError):raise
            if isinstance(cause,(TypeError,ValueError)):raise OfficeKitError('invalid-request',str(cause),cause=cause) from None
            code=getattr(cause,'code',None)
            if code in ('input-too-large','output-too-large','invalid-document','unsupported-format','invalid-output','timeout','unavailable'):raise OfficeKitError(code,getattr(cause,'message',str(cause)),cause=cause) from None
            raise OfficeKitError('failed','LibreOffice conversion failed.',cause=cause) from None
        finally:
            try:
                if directory is not None:await _io(_remove_tree,directory)
            finally:slot.busy=False

    async def readFile(self,path,format,signal):
        try:return await (read_pdf if format=='pdf' else read_output)(path,self.config['maxOutputBytes'],signal)
        except OfficeKitError:raise
        except Exception as cause:raise OfficeKitError('invalid-output','The converter output could not be read.',cause=cause) from None

    async def runEngine(self,converter,input_path,directory,operation,signal):
        kind=operation['kind']
        if kind=='images':return await self.renderPng(converter,input_path,directory,operation,signal)
        if kind not in ('pdf','convert','recalculate'):raise RuntimeError('Unexpected Office operation: '+stringify_json(operation))
        format='pdf' if kind=='pdf' else operation['format'];output_path=os.path.join(directory,'converted.pdf' if kind=='pdf' else 'output.'+format)
        options=dict(inputPath=input_path,outputPath=output_path)
        if kind=='convert' and 'sheet' in operation:options['sheet']=operation['sheet']
        method='render' if kind=='pdf' else kind;result=await await_callback_result(field(converter,method)(options,signal))
        data=await self.readFile(output_path,format,signal);value=dict(kind='pdf' if kind=='pdf' else 'file',missingFonts=field(result,'missingFonts'));value['pdf' if kind=='pdf' else 'data']=data
        if kind!='pdf' and field(result,'pageCount') is not None:value['pageCount']=field(result,'pageCount')
        return value

    async def renderPng(self,converter,input_path,directory,operation,signal):
        output_dir=os.path.join(directory,'images');options=dict(inputPath=input_path,outputDir=output_dir,maxPages=operation['maxImages'],maxPixels=operation['maxPixels'],maxDimension=operation['maxDimension'])
        for key in ('pages','sheet','range','dpi'):
            if key in operation:options[key]=operation[key]
        result=await await_callback_result(field(converter,'renderImages')(options,signal));declared=sum(field(image,'byteLength') for image in field(result,'images'))
        if declared>operation['maxBytes']:raise OfficeKitError('output-too-large','The rendered images total {} bytes, above the {}-byte limit.'.format(declared,operation['maxBytes']))
        images=[];remaining=operation['maxBytes']
        for image in sorted(field(result,'images'),key=lambda image:field(image,'index')):
            try:within=os.path.relpath(field(image,'path'),output_dir)
            except ValueError:within=os.pardir
            if within in ('',os.curdir,os.pardir) or within.startswith(os.pardir+os.sep) or os.path.isabs(within):raise OfficeKitError('invalid-output','The converter reported an image outside its output directory.')
            try:png=await read_png(field(image,'path'),remaining,signal)
            except OfficeKitError:raise
            except Exception as cause:raise OfficeKitError('invalid-output','The rendered image could not be read.',cause=cause) from None
            remaining-=len(png);value=dict(png=png,width=field(image,'width'),height=field(image,'height'))
            for key in ('page','sheet','range'):
                if field(image,key) is not None:value[key]=field(image,key)
            images.append(value)
        return dict(kind='images',images=images,pageCount=field(result,'pageCount'),dpi=field(result,'dpi'),missingFonts=field(result,'missingFonts'))
