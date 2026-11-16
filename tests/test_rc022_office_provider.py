import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio

from dsh.core.abort import AbortController
from dsh.office.current import CurrentOfficeKit,DEFAULTS
from dsh.office.errors import OfficeKitError
from dsh.office.output import PNG_SIGNATURE
from dsh.office.outputs import _native
from dsh.typert.remote import RemoteError
from test_rc022_workspace_preview import setup

PDF=b'%PDF-1.7\npreview\n%%EOF\n'


class Engine:
    def __init__(self):self.created=[];self.calls=[];self.closed=0;self.scratch=[];self.failure=None;self.bad_image=False;self.bad_pdf=False;self.entered=asyncio.Event();self.gate=None
    async def createConverter(self,options):self.created.append(options);return self
    async def render(self,options,signal):
        self.calls.append(('pdf',options));self.scratch.append(str(Path(options['inputPath']).parent));self.entered.set()
        if self.gate is not None:await self.gate.wait()
        if self.failure is not None:raise self.failure
        Path(_native(options['outputPath'])).write_bytes(b'bad' if self.bad_pdf else PDF);return dict(missingFonts=['Font'])
    async def convert(self,options,signal):
        self.calls.append(('convert',options));self.scratch.append(str(Path(options['inputPath']).parent));Path(_native(options['outputPath'])).write_bytes(b'text');return dict(missingFonts=['Font'],pageCount=2)
    async def recalculate(self,options,signal):
        self.calls.append(('recalculate',options));self.scratch.append(str(Path(options['inputPath']).parent));Path(_native(options['outputPath'])).write_bytes(b'xlsx');return dict(missingFonts=[])
    async def renderImages(self,options,signal):
        self.calls.append(('images',options));self.scratch.append(str(Path(options['inputPath']).parent));directory=Path(options['outputDir']);directory.mkdir();rows=[]
        for number in (2,1):
            path=directory/(str(number)+'.png');path.write_bytes(PNG_SIGNATURE+bytes([number]));rows.append(dict(index=number,path=str(path),width=10,height=20,page=number,byteLength=9))
        if self.bad_image:rows[0]['path']=str(directory.parent/'outside.png')
        return dict(images=rows,pageCount=2,dpi=96,missingFonts=['Font'])
    async def dispose(self):self.closed+=1


@pytest_asyncio.fixture
async def provider(tmp_path):
    (tmp_path/'report.DOCX').write_bytes(b'PK\x03\x04');ctx=await setup(tmp_path);engine=Engine();ctx.set_service('officeKitEngine',engine)
    await ctx.plugin(CurrentOfficeKit,dict(outputDirectory=str(tmp_path/'outputs')))
    yield ctx,engine
    if engine.gate is not None:engine.gate.set()
    await ctx.fiber.dispose()
    assert not any(os.path.exists(_native(path)) for path in engine.scratch)


def source(key='source',data=b'PK\x03\x04'):
    async def read(signal,maximum):return dict(bytes=data,version='v1')
    return dict(extension='docx',priority='foreground',source=dict(key=key,version='v1',bytes=len(data),read=read))


@pytest.mark.asyncio
async def test_authorized_preview_reuses_converter_and_cache_after_auth_each_time(provider,tmp_path):
    ctx,engine=provider;scope=dict(sessionId='session',workspaceRoot=str(tmp_path));signal=AbortController().signal
    one=await ctx.officeKit.render(scope,'report.DOCX','foreground',signal);two=await ctx.officeKit.render(scope,'report.DOCX','foreground',signal)
    assert one['data']==PDF and one['bytes']==len(PDF) and one['eof'] and one['missingFonts']==['Font']
    assert one['generation']==ctx.officeKit.getGeneration(signal) and two['version']==one['version']
    assert len(engine.created)==1 and len(engine.calls)==1 and ctx.get('agents') is None
    assert not any(os.path.exists(path) for path in engine.scratch)
    (tmp_path/'report.DOCX').unlink()
    with pytest.raises(RemoteError) as error:await ctx.officeKit.render(scope,'report.DOCX','foreground',signal)
    assert error.value.code=='workspace-file/not-found' and len(engine.calls)==1


@pytest.mark.asyncio
async def test_file_and_image_operations_share_queue_and_retained_owner_outputs(provider):
    ctx,engine=provider;request=source()
    pdf=await ctx.officeKit.convert(request);images=await ctx.officeKit.renderImages(dict(request,maxImages=2,maxPixels=10000,maxDimension=100,maxBytes=18,dpi=96))
    assert pdf['pdf']==PDF and [row['page'] for row in images['images']]==[1,2] and images['images'][0]['png']==PNG_SIGNATURE+b'\x01'
    converted=await ctx.officeKit.convertTo(dict(request,format='txt',sheet='Sheet',output=dict(owner='session',name='../result.txt')))
    recalculated=await ctx.officeKit.recalculate(dict(request,extension='xlsx',format='xlsx',output=dict(owner='other',name='result.xlsx')))
    assert Path(converted['path']).read_bytes()==b'text' and converted['pageCount']==2 and recalculated['bytes']==4
    assert len(engine.created)==1 and [kind for kind,_ in engine.calls]==['pdf','images','convert','recalculate']
    ctx.emit('session/disposed',NS(id='session'));await ctx.officeKit.outputs.settle()
    assert not Path(converted['path']).exists() and Path(recalculated['path']).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('case,code',[('bad-pdf','invalid-output'),('bad-image','invalid-output'),('image-bytes','output-too-large'),('type','invalid-request'),('engine','failed')])
async def test_invalid_engine_outputs_classify_and_clean_scratch(provider,case,code):
    ctx,engine=provider
    if case=='bad-pdf':engine.bad_pdf=True
    if case=='bad-image':engine.bad_image=True
    if case=='type':engine.failure=TypeError('bad selection')
    if case=='engine':engine.failure=RuntimeError('private engine details')
    with pytest.raises(OfficeKitError) as error:
        if case in ('bad-image','image-bytes'):await ctx.officeKit.renderImages(dict(source(),maxImages=2,maxPixels=1000,maxDimension=100,maxBytes=1 if case=='image-bytes' else 18))
        else:await ctx.officeKit.convert(source())
    assert error.value.code==code and not any(os.path.exists(path) for path in engine.scratch) and all(not slot.busy for slot in ctx.officeKit.slots)


@pytest.mark.asyncio
async def test_missing_engine_registers_then_retries_later_without_retaining_failure(provider,tmp_path):
    ctx,engine=provider;ctx.set_service('officeKitEngine',None)
    for _ in range(2):
        with pytest.raises(OfficeKitError) as error:await ctx.officeKit.convert(source())
        assert error.value.code=='unavailable'
    assert len(ctx.officeKit.reported)==1 and not engine.calls
    ctx.set_service('officeKitEngine',engine);assert (await ctx.officeKit.convert(source()))['pdf']==PDF


@pytest.mark.asyncio
async def test_remote_cancel_and_provider_disposal_await_actual_engine_cleanup(provider,tmp_path):
    ctx,engine=provider;engine.gate=asyncio.Event();scope=dict(sessionId='session',workspaceRoot=str(tmp_path));controller=AbortController()
    operation=ctx.officeKit.render(scope,'report.DOCX','foreground',controller.signal);await engine.entered.wait();controller.abort(RuntimeError('caller left'))
    with pytest.raises(RemoteError) as error:await operation
    assert error.value.code=='gateway/cancelled' and ctx.officeKit.queue.running==1
    disposal=asyncio.create_task(ctx.fiber.dispose());await asyncio.sleep(0);assert not disposal.done()
    engine.gate.set();await disposal;assert engine.closed==1 and not any(os.path.exists(path) for path in engine.scratch)


@pytest.mark.asyncio
async def test_remote_format_and_version_gates_do_not_mask_filesystem_errors(provider,tmp_path):
    ctx,engine=provider;scope=dict(sessionId='session',workspaceRoot=str(tmp_path));signal=AbortController().signal
    with pytest.raises(RemoteError) as error:await ctx.officeKit.render(scope,'report.odt','foreground',signal)
    assert error.value.details==dict(reason='unsupported-format') and not engine.calls
    original=ctx.workspaceFiles.stat
    async def changed(*args):value=await original(*args);return dict(value,version='different')
    ctx.workspaceFiles.stat=changed
    with pytest.raises(RemoteError) as error:await ctx.officeKit.render(scope,'report.DOCX','foreground',signal)
    assert error.value.details==dict(reason='source-changed') and not engine.calls


def test_config_defaults_and_bounds():
    value=CurrentOfficeKit.Config.validate({})['value']
    assert all(value[key]==setting for key,setting in DEFAULTS.items()) and 'fontDirectories' not in value and 'fontFallbacks' not in value
    assert CurrentOfficeKit.Config.validate(dict(fontFallbacks=[['Arial','Times']])).get('value')
    for options in (dict(timeoutMs=2147483648),dict(maxInputBytes=9007199254740991),dict(fontFallbacks=[['Arial',' ']]),dict(maxReaders=0)):
        assert CurrentOfficeKit.Config.validate(options).get('issues')


@pytest.mark.asyncio
async def test_actual_office_artifact_authorized_http_binary_and_generation(provider,tmp_path):
    from test_rc022_workspace_preview import SOURCE,ARTIFACT as WORKSPACE_ARTIFACT,Response
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.auth_current import CurrentBrowserAuth
    from dsh.host.connection.authorized import AuthorizedHostConnection,peer_bridge_handler
    from dsh.typert.artifact import read_generated_artifact
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from scripts.rc022_rpc_http_probe import decode_response
    artifact=SOURCE/'packages/document/office-kit/lib/typert.host.js'
    if not artifact.is_file() or not WORKSPACE_ARTIFACT.is_file():pytest.skip('actual pinned generated artifacts required')
    ctx,engine=provider;server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    auth=CurrentBrowserAuth(ctx,bytes(range(32)),1);connection=AuthorizedHostConnection(ctx,[],auth);ctx.set_service('connection',connection)
    ctx.set_service('appReady',NS(onReady=lambda callback:callback()));await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayService,dict(websocketCompression='none'))
    for path in (WORKSPACE_ARTIFACT,artifact):ctx.typert.register(read_generated_artifact(path))
    server.register('prefix','/api',peer_bridge_handler(connection,connection.create_shared_fetch_handler('/api')));await server.start()
    response=Response();connection.authorize_connect(dict(method='GET',headers=dict(host='127.0.0.1:'+str(server.listened_port)),raw_url='/connect?token='+auth.launch_token),response)
    cookie=response.state['headers']['set-cookie'].split(';')[0];observations=[]
    async def call(method,args):
        endpoint='officeKit/'+method;payload=json.dumps(dict(type='client-request',rpcId='office',method=endpoint,payload=dict(args=args))).encode()
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            headers='POST /api/'+endpoint+' HTTP/1.1\r\nHost: 127.0.0.1:'+str(server.listened_port)+'\r\nCookie: '+cookie+'\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(payload))+'\r\n\r\n'
            writer.write(headers.encode()+payload);await writer.drain();raw=await asyncio.wait_for(reader.read(),3);head,body=raw.split(b'\r\n\r\n',1);lines=head.decode().split('\r\n');headers={key.lower():value.strip() for key,value in (line.split(':',1) for line in lines[1:])}
            result=decode_response(dict(status=int(lines[0].split()[1]),headers=headers,body=body));observations.append(result);return result
        finally:writer.close();await writer.wait_closed()
    try:
        generation=await call('generation',{});assert generation['body']['result']==dict(ok=True,value=ctx.officeKit.generation)
        args=dict(workspaceFileScopeId='session',path='report.DOCX',priority='foreground');rendered=await call('render',args)
        assert rendered['metadata']['result']['ok'] and rendered['metadata']['attachments']==[dict(path=['data'],codec='bytes',part='bytes-0')]
        assert rendered['parts'][0]['bytes']==list(PDF) and rendered['metadata']['result']['value']['generation']==ctx.officeKit.generation
        assert ctx.get('agents') is None and len(engine.calls)==1
        invalid=await call('render',dict(args,priority='invalid'));assert invalid['body']['result']['error']['code']=='gateway/input-invalid'
        missing=await call('render',dict(args,workspaceFileScopeId='missing'));assert missing['body']['result']['error']['code']=='gateway/lookup-not-found'
        unsupported=await call('render',dict(args,path='report.odt'));assert unsupported['body']['result']['error']['details']==dict(reason='unsupported-format')
    finally:
        (tmp_path/'office-wire-observations.json').write_text(json.dumps(dict(artifactSha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),observations=observations),indent=2,default=lambda value:list(value) if isinstance(value,bytes) else repr(value)),encoding='utf-8')
        await server.stop()
