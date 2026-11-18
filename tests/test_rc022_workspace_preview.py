import asyncio
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.api.workspace_files_022 import CurrentWorkspaceFiles022
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session.current_session import CurrentSessionPlugin
from dsh.fs.local_current import CurrentFileSystem
from dsh.host.connection.authorized import AuthorizedHostConnection,peer_bridge_handler
from dsh.host.connection.auth_current import CurrentBrowserAuth
from dsh.host.webserver.webserver import WebServerService
from dsh.typert.artifact import read_generated_artifact
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.gateway_authorized import AuthorizedGatewayService
from dsh.typert.remote import RemoteError,remote_methods
from dsh.typert.remote_access import RemoteAccessService
from dsh.typert.stores import field
from scripts.rc022_connection_auth_probe import Response
from scripts.rc022_rpc_http_probe import decode_response


SOURCE=Path(os.environ.get('DSH_RC022_SOURCE',str(Path(__file__).resolve().parents[1]/'reference')))
ARTIFACT=SOURCE/'packages/api/workspace-files/lib/typert.host.js'


async def setup(root,**caps):
    ctx=Context();await ctx.plugin(CurrentSessionPlugin);await ctx.plugin(CurrentTypertRegistry)
    ctx.set_service('fs',CurrentFileSystem(str(root)))
    ctx.set_service('sandboxPolicy',SimpleNamespace(workspaceRoot=str(root)))
    await ctx.plugin(CurrentWorkspaceFiles022,caps)
    ctx.sessions.create('session',dict(meta=dict(cwd=str(root))))
    return ctx


@pytest.mark.asyncio
async def test_actual_native_complete_window_related_bytes_and_size_failures(tmp_path):
    (tmp_path/'base.html').write_bytes(b'base');(tmp_path/'data.bin').write_bytes(bytes(range(10)))
    ctx=await setup(tmp_path,maxBytes=4,maxFileBytes=8);signal=AbortController().signal;scope=dict(sessionId='session',workspaceRoot=str(tmp_path))
    try:
        api=ctx.workspaceFiles
        (tmp_path/'small.bin').write_bytes(b'\x00\x80\xff')
        full=await api.readBytes(scope,'small.bin',{},signal)
        assert full['data']==b'\x00\x80\xff' and full['offset']==0 and full['eof']
        for offset,data,eof in [(0,b'\x00\x01\x02\x03',False),(8,b'\x08\x09',True),(10,b'',True)]:
            result=await api.readBytes(scope,'data.bin',dict(baseFile='base.html',range=dict(offset=offset)),signal)
            assert result['data']==data and result['eof'] is eof and result['offset']==offset
        with pytest.raises(RemoteError) as failure:await api.readBytes(scope,'data.bin',{},signal)
        assert failure.value.code=='workspace-file/too-large' and failure.value.cause.code=='FS_TOO_LARGE'
        lookup=ctx.typert.lookups.get('workspaceFileScope')
        assert field(lookup,'resource')=='session' and await field(lookup,'resolve')('session')==scope
        assert await field(lookup,'resolve')('missing') is None and ctx.get('agents') is None
        names={row['method'] for row in remote_methods(api)}
        assert not {'readAll','readRelated'}&names
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['','/absolute','C:drive','https://host/file','\\server','bad\0name'])
async def test_base_file_only_accepts_relative_paths_before_any_lookup(tmp_path,path):
    ctx=await setup(tmp_path)
    try:
        with pytest.raises(RemoteError) as failure:
            await ctx.workspaceFiles.readBytes(dict(workspaceRoot=str(tmp_path)),path,dict(baseFile='missing'),AbortController().signal)
        assert failure.value.code=='gateway/bad-request' and failure.value.message=='path must be relative when baseFile is provided'
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_full_file_backend_rechecks_growth_and_does_not_use_range(tmp_path):
    (tmp_path/'grow').write_bytes(b'abc');ctx=await setup(tmp_path,maxFileBytes=4);signal=AbortController().signal
    def grow(target):Path(target.targetKey).write_bytes(b'abcdef')
    ctx.fs.internals.inspectReadBytesAfterStat=grow
    try:
        with pytest.raises(RemoteError) as failure:await ctx.workspaceFiles.readBytes(dict(workspaceRoot=str(tmp_path)),'grow',{},signal)
        assert failure.value.code=='workspace-file/too-large'
    finally:await ctx.fiber.dispose()


@pytest.mark.skipif(os.name!='nt',reason='Windows directory junction semantics')
@pytest.mark.asyncio
async def test_actual_junction_directory_listing_confines_resolved_target(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir();inside=workspace/'sub';inside.mkdir();outside=tmp_path/'outside';outside.mkdir()
    (inside/'item').write_bytes(b'x');(outside/'secret').write_bytes(b'other')
    for name,target in [('in-link',inside),('out-link',outside)]:
        result=subprocess.run(['cmd.exe','/c','mklink','/J',str(workspace/name),str(target)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        assert result.returncode==0,result.stderr
    ctx=await setup(workspace);signal=AbortController().signal;scope=dict(workspaceRoot=str(workspace))
    try:
        entry=await ctx.fs.lstat('in-link',dict(cwd=str(workspace)),signal)
        assert entry.type=='symlink'
        result=await ctx.workspaceFiles.list(scope,'in-link',signal)
        assert result['path']=='sub' and result['entries']==[dict(name='item',type='file',size=1)]
        with pytest.raises(RemoteError) as failure:await ctx.workspaceFiles.list(scope,'out-link',signal)
        assert failure.value.code=='workspace-file/outside-workspace'
        with pytest.raises(RemoteError) as failure:await ctx.workspaceFiles.readBytes(scope,'in-link',{},signal)
        assert failure.value.details['kind']=='symlink'
    finally:
        await ctx.fiber.dispose()
        for name in ('in-link','out-link'):os.rmdir(str(workspace/name))


@pytest.mark.asyncio
async def test_original_generated_lookup_and_real_http_multipart_byte_response(tmp_path):
    if not ARTIFACT.is_file():pytest.skip('actual pinned workspace artifact required')
    (tmp_path/'bytes.bin').write_bytes(b'\x00\x80\xff');ctx=await setup(tmp_path,maxFileBytes=4)
    server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    auth=CurrentBrowserAuth(ctx,bytes(range(32)),1);connection=AuthorizedHostConnection(ctx,[],auth)
    ctx.set_service('connection',connection);ctx.set_service('appReady',SimpleNamespace(onReady=lambda callback:callback()))
    await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayService,dict(websocketCompression='none'))
    retire=ctx.typert.register(read_generated_artifact(ARTIFACT))
    server.register('prefix','/api',peer_bridge_handler(connection,connection.create_shared_fetch_handler('/api')))
    await server.start()
    writer=Response();connection.authorize_connect(dict(method='GET',headers=dict(host='127.0.0.1:'+str(server.listened_port)),raw_url='/connect?token='+auth.launch_token),writer)
    cookie=writer.state['headers']['set-cookie'].split(';')[0];observations=[]
    async def call(args,method='readBytes'):
        endpoint='workspaceFiles/'+method;payload=json.dumps(dict(type='client-request',rpcId='bytes',method=endpoint,payload=dict(args=args))).encode()
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            headers='POST /api/'+endpoint+' HTTP/1.1\r\nHost: 127.0.0.1:'+str(server.listened_port)+'\r\nCookie: '+cookie+'\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(payload))+'\r\n\r\n'
            writer.write(headers.encode()+payload);await writer.drain();raw=await asyncio.wait_for(reader.read(),3)
            head,body=raw.split(b'\r\n\r\n',1);lines=head.decode().split('\r\n');headers={key.lower():value.strip() for key,value in (line.split(':',1) for line in lines[1:])}
            result=decode_response(dict(status=int(lines[0].split()[1]),headers=headers,body=body));observations.append(result);return result
        finally:writer.close();await writer.wait_closed()
    try:
        args=dict(workspaceFileScopeId='session',path='bytes.bin',options={});result=await call(args)
        assert result['media']=='multipart/form-data' and result['metadata']['result']['ok'],result
        assert result['parts'][0]['bytes']==[0,128,255] and result['metadata']['attachments']==[dict(path=['data'],codec='bytes',part='bytes-0')]
        assert result['metadata']['result']['value']['data'] is None and ctx.get('agents') is None
        empty=await call(dict(args,options=dict(range=dict(offset=3,length=1))))
        assert empty['parts'][0]['bytes']==[] and empty['metadata']['result']['value']['eof']
        missing=await call(dict(args,workspaceFileScopeId='missing'))
        assert missing['body']['result']['error']['code']=='gateway/lookup-not-found'
        invalid=await call(dict(args,options=dict(range=dict(offset='bad'))))
        assert invalid['body']['result']['error']['code']=='gateway/input-invalid'
        retire();retired=await call(args)
        assert retired['body']['result']['error']['code']=='gateway/definition-unavailable'
    finally:
        try:(tmp_path/'workspace-preview-wire-observations.json').write_text(json.dumps(observations,indent=2,default=lambda value:list(value) if isinstance(value,bytes) else repr(value)),encoding='utf-8')
        finally:await server.stop();await ctx.fiber.dispose()
