"""Pair actual authorized Gateway HTTP and WebSocket method composition."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_duplex_mux_probe import Client
from scripts.rc022_rpc_http_probe import decode_response


async def observe():
    from dsh.cordis import Context
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_transport import AuthorizedGatewayTransport
    from dsh.typert.remote import Remote,TypertRemoteService
    from dsh.typert.artifact import Schema
    ctx=Context();records={};ready_callbacks=[]
    def modify(key,mutate):
        value=mutate(records.get(key))
        if value is not None:records[key]=value
        return records.get(key)
    ctx.set_service('credentials',SimpleNamespace(modify_record=modify))
    def on_ready(callback):ready_callbacks.append(callback);return lambda:ready_callbacks.remove(callback) if callback in ready_callbacks else None
    ctx.set_service('appReady',SimpleNamespace(onReady=on_ready))
    await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService)
    gateway=await ctx.plugin(AuthorizedGatewayTransport,dict(streamInboxBytes=512,websocketCompression='none'))
    retired=asyncio.Event();release=asyncio.Event();hold=False
    class Fixture(TypertRemoteService):
        def __init__(self,child):super().__init__(child,'fixture')
        @Remote
        def info(self):return dict(data=b'abc')
        @Remote(dict(mode='stream'))
        async def echo(self,signal):
            try:
                invocation=self.ctx.invocation
                yield dict(ready=True,kind=invocation.peer.principal['kind'],interactions=invocation.peer.interactions,window=invocation.uplinkWindow)
                async for value in invocation.uplink():yield dict(echo=value,signal=signal is invocation.signal)
            finally:
                retired.set()
                if hold:await release.wait()
    await ctx.plugin(Fixture)
    ctx.typert.register(dict(package='fixture',face='host',model={},schemas=[],invocations=[dict(id='fixture#echo',service='fixture',namespace='fixture',method='echo',mode='stream',parameters=[],cancellation=dict(parameter='signal'),invocation=dict(kind='direct'),result=dict(mode='src-json'),uplink=dict(codec=dict(mode='strict',typeSymbol='Number',schema=Schema('number'))))]))
    await ctx.plugin(AuthorizedConnectionPlugin)
    server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    async def mounted():
        while server.match('/connect') is None or not ready_callbacks:await asyncio.sleep(0)
    await asyncio.wait_for(mounted(),1);await server.start();connection=ctx.connection;rows=[];client=None
    async def http(path,body=None,cookie=None,upgrade=False,host=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            headers=('POST' if body is not None else 'GET')+' '+path+' HTTP/1.1\r\nHost: '+(host or '127.0.0.1:'+str(server.listened_port))+'\r\n'
            if cookie:headers+='Cookie: '+cookie+'\r\n'
            if upgrade:headers+='Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: AAAAAAAAAAAAAAAAAAAAAA==\r\n'
            else:headers+='Connection: close\r\n'
            data=json.dumps(body).encode() if body is not None else b''
            if body is not None:headers+='Content-Type: application/json\r\nContent-Length: '+str(len(data))+'\r\n'
            writer.write(headers.encode()+b'\r\n'+data);await writer.drain()
            try:raw=await asyncio.wait_for(reader.read(),2)
            except ConnectionError:
                if upgrade:return dict(status='closed',headers={},body=b'')
                raise
            if not raw and upgrade:return dict(status='closed',headers={},body=b'')
            head,data=raw.split(b'\r\n\r\n',1);lines=head.decode().split('\r\n');mapped={k.lower():v.strip() for k,v in (line.split(':',1) for line in lines[1:])}
            return dict(status=int(lines[0].split()[1]),headers=mapped,body=data)
        finally:writer.close();await writer.wait_closed()
    async def unary(cookie):return await http('/api/fixture/info',dict(type='client-request',rpcId='id',method='fixture/info',payload=dict(args={})),cookie)
    try:
        rows.append(dict(name='readiness',before=(await http('/api/remote.mux',upgrade=True))['status']))
        for callback in list(ready_callbacks):callback()
        rows.append(dict(name='upgrade-fences',unknown=(await http('/api/remote.mux',upgrade=True))['status'],untrusted=(await http('/api/remote.mux',upgrade=True,host='evil.example'))['status']))
        token=connection.browser_auth.launch_token
        exchanged=await http('/connect?token='+token);cookie=exchanged['headers']['set-cookie'].split(';')[0]
        rows.append(dict(name='http-binary',response=decode_response(await unary(cookie))))
        client=await Client().connect(server.listened_port,cookie=cookie)
        rows.append(dict(name='socket-claim',duplicate=(await http('/api/remote.mux',cookie=cookie,upgrade=True))['status'],http=(await unary(cookie))['status']))
        await client.send(dict(type='open',streamId='good-中',endpoint='fixture/echo',payload=dict(args={})))
        frames=[await client.receive()];await client.send(dict(type='item',streamId='good-中',value=7));frames.append(await client.receive());await client.send(dict(type='end',streamId='good-中'));frames.append(await client.receive())
        rows.append(dict(name='strict-good',frames=frames))
        await client.send(dict(type='open',streamId='bad',endpoint='fixture/echo',payload=dict(args={})))
        frames=[await client.receive()];await client.send(dict(type='item',streamId='bad',value='bad'));frames.append(await client.receive())
        rows.append(dict(name='strict-bad',frames=frames))
        retired.clear();hold=True
        await client.send(dict(type='open',streamId='held',endpoint='fixture/echo',payload=dict(args={})));await client.receive();await client.close();client=None
        await asyncio.wait_for(retired.wait(),2)
        async def revoked():
            while connection.admit(dict(headers=dict(host='127.0.0.1:'+str(server.listened_port),cookie=cookie))).get('rejection')!=401:await asyncio.sleep(0)
        await asyncio.wait_for(revoked(),2)
        rows.append(dict(name='revoked-before-retirement',upgrade=(await http('/api/remote.mux',cookie=cookie,upgrade=True))['status'],held=not release.is_set()))
        release.set();await gateway.dispose()
        fresh=await http('/connect?token='+token);fresh_cookie=fresh['headers']['set-cookie'].split(';')[0]
        rows.append(dict(name='unloaded',upgrade=(await http('/api/remote.mux',cookie=fresh_cookie,upgrade=True))['status'],rpc=(await unary(fresh_cookie))['status']))
        return rows
    finally:
        release.set()
        if client is not None:await client.close()
        await server.stop();await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_gateway_transport.mts','Actual Registry, RemoteAccess, Gateway, Connection, credentials and WebServer composition: readiness gate, HTTP binary RPC, single API socket, actual Remote duplex/strict uplink, credential revocation before slow stream retirement, and reversible carrier unload. Forwarded events remain separate.',[Path(__file__).resolve(),ROOT/'dsh/typert/gateway_transport.py',ROOT/'dsh/typert/gateway_core.py',ROOT/'dsh/typert/duplex_mux.py'])
