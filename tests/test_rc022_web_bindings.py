import asyncio
import json
from pathlib import Path

import pytest

from dsh.boot.app_boot import boot
from dsh.boot.plugin_registry import _load
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES
from dsh.typert.artifact import read_generated_artifact
from scripts.rc022_duplex_mux_probe import Client
from test_rc022_manager_wire import http,SOURCE


@pytest.mark.asyncio
async def test_loader_candidate_authenticated_web_services_with_real_credentials(tmp_path):
    config=tmp_path/'root.json';config.write_text('[]',encoding='utf-8')
    packages=['credentials-local','typert-registry','api-remote-access','api-gateway','api-remotes','client-connection','host-webserver']
    rows=[dict(id=name,name='@deepseek-ai/dsh-'+name,config=dict(path=str(tmp_path/'credentials.yaml')) if name=='credentials-local' else dict(host='127.0.0.1',port=0) if name=='host-webserver' else dict(websocketCompression='none') if name=='api-gateway' else {}) for name in packages]
    def prepare(ctx):
        for package,spec in CURRENT_HARNESS_PLUGIN_CLASSES.items():
            if package in {row['name'] for row in rows}:ctx.loader.harness_plugins[package]=_load(package,spec)
        def typert(child):
            child.effect(lambda:child.typert.register(read_generated_artifact(SOURCE/'packages/api/remote-access/lib/typert.host.js')))
        ctx.inject(['typert'],typert)
    ctx=await boot('candidate-web',str(config),[dict(insert=rows)],prepare);client=None;port=None
    try:
        server=ctx.webServer;port=server.listened_port
        assert port>0 and server.match('/connect') is not None
        denied=await http(server,'/api/remoteAccess/follow',dict(type='client-request',rpcId='unauth',method='remoteAccess/follow',payload=dict(args={})))
        assert denied['status']==401
        response=await http(server,'/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        assert response['status']==302,response
        cookie=response['headers']['set-cookie'].split(';')[0]
        client=await Client().connect(port,cookie=cookie)
        listeners=len(ctx.remoteAccess.lifetime.signal._listeners)
        await client.send(dict(type='open',streamId='access',endpoint='remoteAccess/follow',payload=dict(args={})))
        baseline=await client.receive()
        assert baseline['type']=='item' and baseline['value']==dict(type='baseline',owner=True),baseline
        await client.send(dict(type='cancel',streamId='access'))
        async def released():
            while len(ctx.remoteAccess.lifetime.signal._listeners)!=listeners:await asyncio.sleep(0)
        await asyncio.wait_for(released(),3)
        assert (tmp_path/'credentials.yaml').is_file()
        assert ctx.credentials.filepath==str(tmp_path/'credentials.yaml')
        observations=dict(packages=packages,unauthenticated=denied['status'],connect=response['status'],baseline=baseline,cancelReleased=True,credentialsFileCreated=True)
        (tmp_path/'candidate-web-wire-observations.json').write_text(json.dumps(observations,indent=2),encoding='utf-8')
    finally:
        if client is not None:await client.close()
        await ctx.fiber.dispose()
    with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',port)
