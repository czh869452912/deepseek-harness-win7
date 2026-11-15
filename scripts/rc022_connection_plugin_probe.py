"""Pair real HTTP and reversible candidate Connection plugin composition."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
    from dsh.host.connection.http_bridge import write_response
    ctx=Context();records={};modifies=[]
    def modify(key,mutate):
        modifies.append(1);value=mutate(records.get(key))
        if value is not None:records[key]=value
        return records.get(key)
    ctx.set_service('credentials',SimpleNamespace(modify_record=modify))
    fiber=await ctx.plugin(AuthorizedConnectionPlugin,dict(maxRequestBodyBytes=1024,recovery=dict(backoffFactor=1)))
    connection=ctx.connection;rows=[dict(name='headless',available=connection is not None,web=ctx.get('webServer') is not None)]
    server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    async def mounted():
        while server.match('/connect') is None:await asyncio.sleep(0)
    await asyncio.wait_for(mounted(),1);await server.start()
    trace=[];blocked=False
    async def middleware(request,writer,next_fn):
        trace.append('before')
        if blocked:
            trace.append('refused');await write_response(writer,dict(status=503,body='paused'));return
        await next_fn();trace.append('after')
    ctx.on('connection/request',middleware)
    async def handler(endpoint,payload,signal,peer):
        trace.append('handler');return dict(ok=True,value=dict(endpoint=endpoint,kind=peer.principal['kind'],interactions=peer.interactions,payload=payload))
    connection.rpc.intercept('/api',lambda _:True,handler)
    async def exchange(path,method='GET',cookie=None,body=None,length=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            data=body or b'';text=method+' '+path+' HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n'
            if cookie:text+='Cookie: '+cookie+'\r\n'
            if body is not None or length is not None:text+='Content-Type: application/json\r\nContent-Length: '+str(length if length is not None else len(data))+'\r\n'
            writer.write(text.encode()+b'\r\n'+data);await writer.drain();raw=await asyncio.wait_for(reader.read(),2)
            head,payload=raw.split(b'\r\n\r\n',1);lines=head.decode().split('\r\n');headers={k.lower():v.strip() for k,v in (line.split(':',1) for line in lines[1:])}
            return dict(status=int(lines[0].split()[1]),headers=headers,body=payload.decode())
        finally:writer.close();await writer.wait_closed()
    try:
        table=[];ctx.emit('webserver/index-inject',table)
        rows.append(dict(name='mounted',connect=server.match('/connect').kind,api=server.match('/api/run').kind,recovery=table))
        result=await exchange('/api/run','POST',length=999999);rows.append(dict(name='unauthenticated',status=result['status'],body=result['body'],trace=list(trace)))
        token=connection.browser_auth.launch_token
        result=await exchange('/connect?token='+token);cookie=result['headers']['set-cookie'].split(';')[0]
        rows.append(dict(name='connect',status=result['status'],location=result['headers']['location'],trace=list(trace)))
        payload=dict(args={},peer=dict(kind='forged'))
        result=await exchange('/api/run','POST',cookie,json.dumps(dict(type='client-request',rpcId='id',method='run',payload=payload)).encode())
        rows.append(dict(name='rpc',status=result['status'],body=json.loads(result['body']),trace=list(trace)))
        blocked=True;trace.clear();result=await exchange('/api/run','POST',cookie,length=999999)
        rows.append(dict(name='blocked',status=result['status'],body=result['body'],trace=list(trace)))
        await fiber.dispose();table=[];ctx.emit('webserver/index-inject',table)
        rows.append(dict(name='unloaded',connection=ctx.get('connection') is not None,connect=server.match('/connect') is not None,api=server.match('/api/run') is not None,injections=table,browserAborted=connection.browserPeer.signal.aborted))
        replacement=await ctx.plugin(AuthorizedConnectionPlugin)
        rows.append(dict(name='reloaded',sameToken=ctx.connection.browser_auth.launch_token==token,sameSecret=ctx.connection.browser_auth.secret==connection.browser_auth.secret,modifies=len(modifies),records=len(records)))
        await replacement.dispose()
        return rows
    finally:await server.stop();await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_connection_plugin.mts','Actual late WebServer mounting and real HTTP through upstream/candidate Connection plugins: persisted credential provider, headless activation, /connect exchange, shared RPC peer, middleware covers body transfer and response, refusal before body, unload/reload and recovery injection.',[Path(__file__).resolve(),ROOT/'dsh/host/connection/plugin_current.py',ROOT/'dsh/host/connection/authorized.py'])
