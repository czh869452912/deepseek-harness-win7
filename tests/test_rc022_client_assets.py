import asyncio
import builtins
import json

import pytest

from dsh.cordis import Context
from dsh.host.client_modules.current import CurrentClientModulesPlugin
from dsh.host.webserver.current import CurrentWebServerPlugin
from scripts.rc022_client_assets_probe import NAME,prepare,loader,observe,response_bytes


@pytest.mark.asyncio
async def test_current_asset_observations(tmp_path):
    prepare(tmp_path);rows=await observe(tmp_path/'files')
    (tmp_path/'client-assets-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    stages={row['stage']:row for row in rows}
    assert len(rows)==24
    assert stages['large']['length']==160*1024
    assert stages['svg']['headers']['content-security-policy']=="script-src 'none'"
    assert stages['head']['headers']==stages['svg']['headers'] and stages['head']['length']==0
    assert stages['not-modified']['status']==304 and stages['not-modified']['length']==0
    assert stages['weak-etag']['status']==200
    assert all(row['status']==404 for row in rows[10:])


@pytest.mark.asyncio
async def test_current_asset_http_resource_and_direct_carriers_close_files(tmp_path,monkeypatch):
    prepare(tmp_path);workspace=tmp_path/'files';ctx=Context();ctx.provide('loader',loader(workspace))
    handles=[];original=builtins.open
    def tracked(path,*args,**kwargs):
        handle=original(path,*args,**kwargs)
        if 'lib/assets' in str(path).replace('\\','/') and args and args[0]=='rb':handles.append(handle)
        return handle
    monkeypatch.setattr(builtins,'open',tracked)
    async def http(path,method='GET',tag=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',ctx.get('webServer').port)
        try:
            request=method+' '+path+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n'
            if tag:request+='If-None-Match: '+tag+'\r\n'
            writer.write((request+'\r\n').encode('ascii'));await writer.drain()
            raw=await asyncio.wait_for(reader.read(),3);head,body=raw.split(b'\r\n\r\n',1)
            lines=head.decode('ascii').split('\r\n');headers={key.lower():value.strip() for key,value in (line.split(':',1) for line in lines[1:])}
            return dict(status=int(lines[0].split()[1]),headers={key:value for key,value in headers.items() if key in
                ['content-type','cache-control','etag','x-content-type-options','content-security-policy']},body=body)
        finally:writer.close();await writer.wait_closed()
    try:
        await ctx.plugin(CurrentWebServerPlugin,dict(host='127.0.0.1',port=0))
        fiber=ctx.plugin(CurrentClientModulesPlugin);await fiber
        server=ctx.get('webServer');registry=ctx.get('clientModules')
        for method,tag in [('GET',None),('HEAD',None),('GET','"large.png"')]:
            path='/plugins/'+NAME+'/assets/large.png'
            via_http=await http(path,method,tag)
            request=dict(url='http://x'+path,method=method,headers={'if-none-match':tag} if tag else {})
            for result in [await server.readResource(request,object()),await registry.fetchBundle(request)]:
                assert dict(result,body=await response_bytes(result))==via_http
            assert handles and all(handle.closed for handle in handles)
        before=len(handles)
        await http('/plugins/'+NAME+'/assets/large.png','HEAD')
        await http('/plugins/'+NAME+'/assets/large.png',tag='"large.png"')
        assert len(handles)==before
        for consume in [False,True]:
            result=await registry.fetchBundle(dict(url='http://x/plugins/'+NAME+'/assets/large.png',method='GET'))
            body=result['body']
            if consume:assert len(await body.__anext__())==64*1024
            await body.aclose();assert (await body.opening).closed
        # Exercise an actual interrupted HTTP transfer, not only direct
        # iterator cancellation. The body is larger than socket backpressure.
        (workspace/'node_modules'/NAME/'lib/assets/cancel.png').write_bytes(b'\7'*(8*1024*1024))
        reader,writer=await asyncio.open_connection('127.0.0.1',server.port)
        try:
            writer.write(('GET /plugins/'+NAME+'/assets/cancel.png HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode('ascii'))
            await writer.drain();await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
            assert await asyncio.wait_for(reader.read(1),3)
        finally:
            writer.transport.abort();await writer.wait_closed()
        async def closed():
            while not all(handle.closed for handle in handles):await asyncio.sleep(.01)
        await asyncio.wait_for(closed(),3)
        await fiber.dispose()
        assert (await server.readResource(dict(url='http://x/plugins/'+NAME+'/assets/photo.png'),object()))['status']==404
    finally:await ctx.fiber.dispose()
    assert all(handle.closed for handle in handles)


@pytest.mark.asyncio
async def test_current_asset_cancel_waits_for_inflight_read_before_close(tmp_path,monkeypatch):
    from dsh.host.client_modules.assets_current import FileBody
    import threading
    started=threading.Event();release=threading.Event();closed=[]
    class Handle:
        def read(self,size):
            started.set();assert release.wait(3);assert not closed;return b'chunk'
        def close(self):closed.append(True)
    monkeypatch.setattr(builtins,'open',lambda *args,**kwargs:Handle())
    body=FileBody('owned.png');task=asyncio.create_task(body.__anext__())
    try:
        await asyncio.get_running_loop().run_in_executor(None,lambda:started.wait(3))
        assert started.is_set();task.cancel();await asyncio.sleep(0)
        assert not closed;release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert closed==[True]
        await body.aclose();assert closed==[True]
    finally:
        release.set()
        await body.aclose()
