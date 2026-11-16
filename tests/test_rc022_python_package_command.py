import asyncio
import json
import threading
import sys
from pathlib import Path

import pytest

from dsh.boot.plugin_package_view import _execute_package_query,view_profile_package
from dsh.boot.python_package_cli import package_command
from dsh.core.abort import AbortController
from scripts.rc022_python_package_command_probe import observe
from scripts.rc022_python_package_query_probe import RegistryFixture


@pytest.mark.asyncio
async def test_actual_manager_queries_use_python_with_no_path_executables(tmp_path):
    rows={row['name']:row['result'] for row in await asyncio.wait_for(observe(tmp_path),30)}
    assert len(rows)==7 and rows['registries']['resolved']=='<registry>/'
    assert rows['inspect']['status']=='accepted' and rows['inspect']['name']=='timed'
    assert rows['scope']['name']==rows['alias']['name']=='@scope/pkg'
    assert rows['known']['problem']=='already-installed'
    assert rows['missing']['status']=='refused'
    assert rows['versions']['status']=='listed'
    assert [row['version'] for row in rows['versions']['versions']]==['2.0.0','2.0.0-beta.2','2.0.0-beta.1','1.2.0']
    assert rows['versions']['versions'][-1]['tags']==['latest']


@pytest.mark.asyncio
async def test_actual_query_adapter_single_fields_missing_stdout_and_error_shape(tmp_path):
    fixture=RegistryFixture()
    try:
        blank=tmp_path/'npmrc';blank.write_text('',encoding='utf-8')
        options=dict(package_command(dict(PATH='',NPM_CONFIG_USERCONFIG=str(blank),npm_config_registry=fixture.url,NO_PROXY='127.0.0.1')),timeoutMs=3000)
        assert Path(options['command']).resolve()==Path(sys.executable).resolve()
        assert options['env']['PATH']==''
        for fields,expected in [(['name'],'fresh'),(['dsh.bundle.patch'],'patch.yml')]:
            result=await view_profile_package(str(tmp_path),'fresh',dict(options,fields=fields))
            assert result['exitCode']==0 and json.loads(result['stdout'])==expected
        result=await view_profile_package(str(tmp_path),'fresh',dict(options,fields=['missing']))
        assert result['exitCode']==0 and result['stdout']==''
        result=await view_profile_package(str(tmp_path),'fresh@8.0.0',dict(options,fields=['name','version']))
        assert result['exitCode']==1 and json.loads(result['stdout'])['error']['code']=='ERR_PNPM_PACKAGE_NOT_FOUND'
        assert 'ERR_PNPM_PACKAGE_NOT_FOUND' in result['stderr']
    finally:fixture.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments,code',[
    (['add','fresh'],'ERR_DSH_PYTHON_PACKAGE_OPERATION_UNAVAILABLE'),
    (['view','fresh','name','--unimplemented'],'ERR_DSH_PACKAGE_ARGUMENT'),
    (['view','fresh','--json'],'ERR_DSH_PACKAGE_ARGUMENT'),
])
async def test_query_adapter_refuses_unavailable_mutations_and_options_without_writing(tmp_path,arguments,code):
    before=b'{"name":"profile","dependencies":{"keep":"1.0.0"}}\r\n';manifest=tmp_path/'package.json';manifest.write_bytes(before)
    options=dict(package_command(dict(PATH='')),timeoutMs=3000)
    result=await _execute_package_query(str(tmp_path),[options['command']]+options['args']+arguments,options)
    assert result['exitCode']==1 and json.loads(result['stdout'])['error']['code']==code
    assert manifest.read_bytes()==before and sorted(path.name for path in tmp_path.iterdir())==['package.json']


@pytest.mark.asyncio
async def test_cancellation_stops_actual_python_metadata_child_during_http_read(tmp_path):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    ready=threading.Event();release=threading.Event();done=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ready.set()
            try:
                release.wait(5);self.send_response(200);self.end_headers()
                try:self.wfile.write(b'{}')
                except OSError:pass
            finally:done.set()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    control=AbortController();blank=tmp_path/'npmrc';blank.write_text('',encoding='utf-8')
    try:
        options=dict(package_command(dict(PATH='',NPM_CONFIG_USERCONFIG=str(blank),npm_config_registry='http://127.0.0.1:'+str(server.server_port)+'/',NO_PROXY='127.0.0.1')),fields=['name','version'],timeoutMs=3000,signal=control.signal)
        task=asyncio.create_task(view_profile_package(str(tmp_path),'fresh',options))
        for _ in range(100):
            if ready.is_set():break
            await asyncio.sleep(.02)
        assert ready.is_set();control.abort()
        result=await asyncio.wait_for(task,3)
        assert result['exitCode'] is None and not result['timedOut']
    finally:
        release.set();server.shutdown();server.server_close();worker.join(timeout=5)
        assert not worker.is_alive() and done.wait(5)
