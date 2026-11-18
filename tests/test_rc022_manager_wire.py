import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.host.webserver.webserver import WebServerService
from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.remote_access import RemoteAccessService
from dsh.typert.gateway_authorized import AuthorizedGatewayService
from dsh.typert.api_remotes_authorized import AuthorizedApiRemotes
from dsh.typert.artifact import read_generated_artifact
from scripts.rc022_duplex_mux_probe import Client
from test_python_plugin_distribution import profile, close, echo, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start

SOURCE=Path(os.environ.get('DSH_RC022_SOURCE', str(Path(__file__).resolve().parents[1]/'reference')))
ARTIFACT=SOURCE/'packages/boot/plugin-manager/lib/typert.host.js'
pytestmark=pytest.mark.skipif(not ARTIFACT.is_file(),reason='actual pinned rc022 generated manager artifact is required')


class WireClient(Client):
    async def event(self):
        while not self.events:
            data=await asyncio.wait_for(self.reader.read(65536),30)
            if not data:return None
            if hasattr(self,'wire'):self.record(data)
            self.codec.receive_data(data);self.events.extend(self.codec.events())
        return self.events.pop(0)


async def http(server,path,body=None,cookie=None):
    reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
    try:
        data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else b''
        text=('POST' if body is not None else 'GET')+' '+path+' HTTP/1.1\r\nHost: 127.0.0.1:'+str(server.listened_port)+'\r\nConnection: close\r\n'
        if cookie:text+='Cookie: '+cookie+'\r\n'
        if body is not None:text+='Content-Type: application/json\r\nContent-Length: '+str(len(data))+'\r\n'
        writer.write(text.encode('utf-8')+b'\r\n'+data);await writer.drain()
        raw=await asyncio.wait_for(reader.read(),30)
        head,data=raw.split(b'\r\n\r\n',1);lines=head.decode().split('\r\n')
        headers={key.lower():value.strip() for key,value in (line.split(':',1) for line in lines[1:])}
        return dict(status=int(lines[0].split()[1]),headers=headers,body=data.decode('utf-8'))
    finally:
        writer.close();await writer.wait_closed()


async def setup_wire(home,state):
    host=await start(home,state);ctx=host['ctx'];server=None;client=None
    try:
        assert ctx.get('typert') is None
        await ctx.plugin(CurrentTypertRegistry)
        host['retire_manager_definition']=ctx.typert.register(read_generated_artifact(ARTIFACT))
        await ctx.plugin(RemoteAccessService)
        records={}
        def modify(key,mutate):
            value=mutate(records.get(key))
            if value is not None:records[key]=value
            return records.get(key)
        assert ctx.get('credentials') is None
        ctx.set_service('credentials',SimpleNamespace(modifyRecord=modify))
        await ctx.plugin(AuthorizedConnectionPlugin)
        gateway=await ctx.plugin(AuthorizedGatewayService,dict(websocketCompression='none'))
        await ctx.plugin(AuthorizedApiRemotes)
        server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
        async def ready():
            while server.match('/connect') is None or '/api/remote.mux' not in server._upgrade_routes:await asyncio.sleep(0)
        await asyncio.wait_for(ready(),3);await server.start()
        exchange=await http(server,'/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        cookie=exchange['headers']['set-cookie'].split(';')[0]
        client=await WireClient().connect(server.listened_port,cookie=cookie)
        await client.send(dict(type='open',streamId='events',endpoint='$events',payload=dict(args={})))
        ready_frame=await client.receive()
        assert ready_frame['type']=='item' and ready_frame['value']['type']=='ready',ready_frame
        return host,server,client,cookie,gateway
    except BaseException:
        if client is not None:await client.close()
        if server is not None:await server.stop()
        await close(host)
        raise


async def rpc(server,cookie,method,args):
    endpoint='pluginManager/'+method
    response=await http(server,'/api/'+endpoint,dict(type='client-request',rpcId=method,method=endpoint,payload=dict(args=args)),cookie)
    assert response['status']==200,response
    payload=json.loads(response['body'])
    return payload['result']


@pytest.mark.asyncio
async def test_actual_generated_manager_http_rpc_and_mux_install_events(profile,registry_package,tmp_path):
    home,directory=profile
    host,server,client,cookie,gateway=await setup_wire(home,registry_package)
    frames=[];results=[]
    async def collect():
        while True:
            frame=await client.receive()
            if 'closed' in frame:return
            frames.append(frame)
    collector=asyncio.create_task(collect())
    async def call(method,args):
        result=await rpc(server,cookie,method,args);results.append(dict(method=method,args=args,result=result));return result
    try:
        listed=await call('listPlugins',{})
        assert listed['ok'] and isinstance(listed['value'],list)
        invalid=await call('setBundleEnabled',dict(name=PACKAGE,enabled='yes'))
        assert not invalid['ok'] and invalid['error']['code']=='gateway/input-invalid',invalid
        installed=await call('installBundle',dict(spec=PACKAGE,options=dict(requestId='wire-install')))
        assert installed['ok'] and installed['value']['application']=='applied',installed
        assert await echo(host['ctx'])=='Python echo: hello'
        listed=await call('listBundles',{})
        assert any(row['name']==PACKAGE and row['enabled'] for row in listed['value'])
        disabled=await call('setBundleEnabled',dict(name=PACKAGE,enabled=False))
        assert disabled['ok'] and disabled['value']['application']=='applied',disabled
        assert host['ctx'].tools.get('python_echo') is None
        enabled=await call('setBundleEnabled',dict(name=PACKAGE,enabled=True))
        assert enabled['ok'] and enabled['value']['application']=='applied',enabled
        assert await echo(host['ctx'])=='Python echo: hello'
        removed=await call('removeBundle',dict(name=PACKAGE))
        assert removed['ok'] and removed['value']['application']=='applied',removed
        for _ in range(100):
            if any(frame.get('value',{}).get('event')=='plugin-manager/changed' for frame in frames):break
            await asyncio.sleep(.01)
        emits=[frame['value'] for frame in frames if frame['type']=='item' and frame['value'].get('type')=='emit']
        names={frame['event'] for frame in emits}
        assert {'plugin-manager/install-log','plugin-manager/install-state','plugin-manager/changed'}<=names
        states=[frame['args'][0] for frame in emits if frame['event']=='plugin-manager/install-state' and frame['args'][0].get('requestId')=='wire-install']
        assert states and any(row['phase']=='applying' for row in states),states
        assert not (directory/'.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
    finally:
        (tmp_path/'manager-wire-observations.json').write_text(json.dumps(dict(artifactSha256=hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),results=results,frames=frames),ensure_ascii=True,indent=2),encoding='utf-8')
        await client.close();collector.cancel();await asyncio.gather(collector,return_exceptions=True)
        await gateway.dispose();await server.stop();await close(host)


@pytest.mark.asyncio
async def test_wire_admission_input_and_definition_retirement(profile,registry_package,tmp_path):
    home,directory=profile
    host,server,client,cookie,gateway=await setup_wire(home,registry_package)
    observations=[]
    try:
        rejected=await http(server,'/api/pluginManager/listPlugins',dict(args={}))
        assert rejected['status']==401
        observations.append(dict(unauthenticatedStatus=rejected['status']))
        assert await rpc(server,cookie,'waitForInstall',dict(requestId='missing'))==dict(ok=True,value=None)
        assert await rpc(server,cookie,'cancelInstall',dict(requestId='missing'))==dict(ok=True,value=dict(status='not-running'))
        invalid=await rpc(server,cookie,'installBundle',dict(spec=PACKAGE,options=dict(requestId=12)))
        assert not invalid['ok'] and invalid['error']['code']=='gateway/input-invalid',invalid
        assert registry_package['requests']==[],registry_package['requests']
        exchange=await http(server,'/connect?token='+host['ctx'].connection.browser_auth.launch_token)
        limited_cookie=exchange['headers']['set-cookie'].split(';')[0]
        limited=await WireClient().connect(server.listened_port,cookie=limited_cookie)
        try:
            await limited.send(dict(type='open',streamId='limited',endpoint='$events',payload=dict(args={})))
            denied=await limited.receive()
            assert denied['type']=='error' and denied['error']['code']=='gateway/interactions-forbidden',denied
            observations.append(denied)
        finally:await limited.close()
        host['retire_manager_definition']()
        retired=await rpc(server,cookie,'listPlugins',{})
        assert not retired['ok'] and retired['error']['code']=='gateway/definition-unavailable',retired
        observations.extend([invalid,retired])
    finally:
        (tmp_path/'manager-wire-observations.json').write_text(json.dumps(observations,ensure_ascii=True,indent=2),encoding='utf-8')
        await client.close();await gateway.dispose();await server.stop();await close(host)
