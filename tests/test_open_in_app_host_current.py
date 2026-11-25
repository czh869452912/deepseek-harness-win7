"""Actual authenticated HTTP transport, bounded input and icon temp ownership."""
import asyncio
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.host.connection.current import CurrentHostConnection
from dsh.host.open_in_app_current import CurrentOpenInApp, resolve_config
from dsh.host.open_in_app_icons_current import extract_app_icon
from dsh.host.native_command_current import run_native_command
from dsh.host.webserver.webserver import WebServerPlugin
from scripts.oracles.open_in_app_host_current_python import execute
from scripts.session_format_oracle import json_equal

CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/open_in_app_host_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_actual_source_open_in_app_host_contract(case):
    assert json_equal(execute(case),case['expected'])


def test_refresh_positive_journeys_really_launch_and_retire_proved_entries():
    lookup={case['case']:case['expected'] for case in CASES}
    for name,app in [('refresh-removes-stale','vscode'),('refresh-removes-file-launcher','github')]:
        value=lookup[name]
        assert app in value['responses'][0]['body']['apps']
        assert value['responses'][1]['status']==502 and len(value['launches'])==1
        assert app not in value['responses'][2]['body']['apps']
    value=lookup['refresh-evicts-icon-cache']
    assert [row['status'] for row in value['responses']]==[200,200,200]
    assert len(value['launches'])==2
    assert [row['command'] for row in value['commands']]==['plutil','sips','plutil','sips']
    cached=lookup['lazy-catalog-icon-launch']
    assert len(cached['launches'])==1 and cached['probes']=={'xcode-select':1}


@pytest.mark.parametrize('key',['probeTimeoutMs','iconTimeoutMs','launchWatchMs'])
@pytest.mark.parametrize('value',[None,True,False,0,-1,0.5,600001,float('inf'),float('nan'),'100'])
def test_config_requires_explicit_bounded_milliseconds(key,value):
    config=dict(probeTimeoutMs=1,iconTimeoutMs=2,launchWatchMs=600000);config[key]=value
    with pytest.raises(ValueError):resolve_config(config)


@pytest.mark.asyncio
async def test_real_tcp_auth_before_body_bounded_chunked_input_and_reversible_routes(tmp_path):
    ctx=Context()
    await ctx.plugin(WebServerPlugin,dict(host='127.0.0.1',port=0))
    server=ctx.get('webServer')
    ctx.set_service('launchEnvironment',LaunchEnvironmentSnapshot([]))
    authenticated=[False];CurrentHostConnection(ctx,[],SimpleNamespace(is_authenticated=lambda _:authenticated[0]))
    calls=[];probes=Counter()
    binary=tmp_path/'editor.exe';binary.write_bytes(b'fixture')
    async def resolve(name):
        probes[name]+=1
        if name=='code':return str(binary)
        raise FileNotFoundError(name)
    async def launch(command,args,options):calls.append((command,args,options))
    ctx.set_service('subprocess',SimpleNamespace(resolveExecutable=resolve))
    class Plugin(CurrentOpenInApp):catalog_internals=dict(platform='linux',home=str(tmp_path),env=dict(XDG_DATA_DIRS=''),launch=launch)
    fiber=await ctx.plugin(Plugin,dict(probeTimeoutMs=1000,iconTimeoutMs=1000,launchWatchMs=25))
    assert server.match('/open-in-app/open').handler.defer_body
    async def fetch(path,method='GET',body=b'',headers=None,declared=None,chunked=False):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            values={'Host':'127.0.0.1','Content-Type':'application/json','Connection':'close'}
            values.update(headers or {})
            if chunked:
                values['Transfer-Encoding']='chunked'
            else:values['Content-Length']=str(len(body) if declared is None else declared)
            head=method+' '+path+' HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in values.items())+'\r\n'
            writer.write(head.encode('ascii'))
            if chunked:
                for part in [body[:3],body[3:]]:
                    if part:writer.write(('%x\r\n'%len(part)).encode('ascii')+part+b'\r\n')
                writer.write(b'0\r\n\r\n')
            else:writer.write(body)
            await writer.drain()
            raw=await asyncio.wait_for(reader.read(),3)
            head,body=raw.split(b'\r\n\r\n',1)
            return int(head.split()[1]),head.lower(),body
        finally:writer.close();await writer.wait_closed()
    try:
        status,headers,body=await fetch('/open-in-app/open','POST',declared=100000000)
        assert status==401 and body==b'' and not probes and not calls
        authenticated[0]=True
        status,_,body=await fetch('/open-in-app/apps',headers={'Host':'untrusted.invalid'})
        assert status==403 and not probes
        status,headers,body=await fetch('/open-in-app/apps')
        assert status==200 and json.loads(body)==dict(apps=['vscode']) and b'cache-control: no-store' in headers
        counts=dict(probes)
        workspace=tmp_path/"a b';literal";workspace.mkdir()
        payload=json.dumps(dict(app='vscode',path=str(workspace),extra='accepted')).encode('utf-8')
        status,_,body=await fetch('/open-in-app/open','POST',payload,chunked=True)
        assert status==200 and json.loads(body)==dict(ok=True)
        assert calls==[(str(binary),[str(workspace)],dict(watchMs=25))] and dict(probes)==counts
        # Readable refusal after crossing 64KiB without waiting for the rest
        # of a declared large request; neither resolution nor launch repeats.
        status,_,body=await fetch('/open-in-app/open','POST',b'x'*70000,declared=100000000)
        assert status==413 and json.loads(body)['code']=='payload-too-large' and len(calls)==1
        status,_,body=await fetch('/open-in-app/open','POST',b'x'*70000,chunked=True)
        assert status==413 and json.loads(body)['code']=='payload-too-large'
        await fiber.dispose()
        for path in ('/open-in-app/apps','/open-in-app/icon/vscode','/open-in-app/open'):
            assert (await fetch(path))[0]==404
        assert not server._exact_routes and not server._prefix_routes
    finally:await server.stop();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_windows_associated_icon_extraction_uses_literal_script_args_and_cleans(tmp_path):
    if os.name!='nt':pytest.skip('Windows System.Drawing extraction')
    owned=[]
    async def run(command,args,signal):
        assert command=='powershell.exe' and args[4]=='-File' and args[-2]==sys.executable
        script,target=Path(args[5]),Path(args[-1]);owned.append(script.parent)
        assert script.parent==target.parent and script.is_file()
        return await run_native_command(command,args,signal)
    async def resolve(_):return None
    value=await extract_app_icon(dict(id='python',platforms={}),dict(launch=dict(kind='argv',command=sys.executable,args=[]),icon=dict(kind='executable',path=sys.executable)),20000,dict(platform='win32',resolveExecutable=resolve,run=run))
    assert value is not None and value['contentType']=='image/png'
    assert value['bytes'].startswith(b'\x89PNG\r\n\x1a\n')
    with Image.open(io.BytesIO(value['bytes'])) as icon:assert icon.width>0 and icon.height>0
    assert owned and all(not path.exists() for path in owned)
