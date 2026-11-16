import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

import pytest

from dsh.boot.plugin_registry_policy import UNSPECIFIED
from dsh.boot.python_package_query import (PackageQueryError,RegistryRedirects,npm_configuration,
    configured_registry,query_metadata,read_packument,_registry_request)
from dsh.boot.semver import satisfies
from scripts.rc022_python_package_query_probe import observe


@pytest.mark.asyncio
async def test_real_registry_selection_tags_ranges_aliases_deprecation_and_fields(tmp_path):
    rows={row['name']:row['result'] for row in await observe(tmp_path)}
    assert len(rows)==18
    assert rows['latest']['version']==rows['range']['version']==rows['star']['version']=='1.2.0'
    assert rows['tag']['version']==rows['prerelease-range']['version']=='2.0.0-beta.2'
    assert rows['exact']['version']=='1.0.0'
    assert rows['v-prefix']==rows['missing']==dict(error='ERR_PNPM_PACKAGE_NOT_FOUND')
    assert rows['scoped']['name']==rows['alias']['name']=='@scope/pkg'
    assert rows['nested-field']=='patch.yml'
    assert rows['missing-field']=={}
    assert 'time' not in rows['listing'] and len(rows['complete-time']['time'])==5
    assert rows['deprecated-latest']['version']=='2.0.0'
    assert rows['deprecated-range']['version']=='1.0.0'
    assert rows['deprecated-exact']['version']=='1.2.0'
    assert rows['empty']==dict(error='ERR_PNPM_NO_VERSIONS')


@contextmanager
def registry(handler):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(dict(path=self.path,auth=self.headers.get('Authorization')))
            status,headers,payload=handler(self.path)
            self.send_response(status)
            for key,value in headers.items():self.send_header(key,value)
            self.end_headers()
            try:self.wfile.write(payload)
            except OSError:pass
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)+'/',requests
    finally:server.shutdown();server.server_close();worker.join(timeout=5);assert not worker.is_alive()


def test_config_precedence_scope_and_environment_expansion(tmp_path):
    user=tmp_path/'user.npmrc';user.write_text('registry=https://user.example/\n//private.example/:_authToken=${TOKEN}\n',encoding='utf-8')
    (tmp_path/'.npmrc').write_text('\ufeff# configuration\nregistry="https://profile.example/"\n@scope:registry=https://private.example/\n',encoding='utf-8')
    config=npm_configuration(str(tmp_path),dict(NPM_CONFIG_USERCONFIG=str(user),TOKEN='fixture',npm_config_registry='https://env.example/'))
    assert configured_registry(config)=='https://env.example/'
    assert config['@scope:registry']=='https://private.example/' and config['//private.example/:_authToken']=='fixture'
    with registry(lambda path:(200,{},b'{"versions":{"1.0.0":{"name":"@scope/pkg","version":"1.0.0"}},"dist-tags":{"latest":"1.0.0"}}')) as (url,requests):
        (tmp_path/'.npmrc').write_text('@scope:registry='+url+'\n',encoding='utf-8')
        assert query_metadata(str(tmp_path),'@scope/pkg',['name'],registry='http://127.0.0.1:1/',env={})=='@scope/pkg'
        assert requests[0]['path']=='/@scope%2Fpkg'


def test_auth_prefix_and_redirect_cannot_forward_registry_token():
    with registry(lambda path:(302,{'Location':'/landing'},b'') if path.startswith('/private/') else (200,{},b'{}')) as (url,requests):
        prefix='//'+url.split('://',1)[1]+'private/'
        assert read_packument('fresh',url+'private/',{prefix+':_authToken':'fixture-secret'})=={}
        assert requests==[dict(path='/private/fresh',auth='Bearer fixture-secret'),dict(path='/landing',auth=None)]
        request=_registry_request(url+'private-other/','fresh',{prefix.rstrip('/')+':_authToken':'fixture-secret'})
        assert request.get_header('Authorization') is None
    request=_registry_request('https://name:p%40ss@example.invalid/','fresh',{})
    assert '@example.invalid' not in request.full_url and request.get_header('Authorization')=='Basic bmFtZTpwQHNz'


@pytest.mark.parametrize('status,headers,payload,limit,code',[
    (404,{},b'',100,'ERR_PNPM_FETCH_404'),
    (403,{},b'',100,'ERR_PNPM_FETCH_403'),
    (503,{},b'',100,'ERR_PNPM_FETCH_503'),
    (200,{},b'{invalid',100,'ERR_PNPM_META_FETCH_FAIL'),
    (200,{},b'{"value":NaN}',100,'ERR_PNPM_META_FETCH_FAIL'),
    (200,{},b'[]',100,'ERR_PNPM_META_FETCH_FAIL'),
    (200,{'Content-Encoding':'gzip'},b'{}',100,'ERR_PNPM_META_FETCH_FAIL'),
    (200,{'Content-Length':'1000'},b'{}',100,'ERR_PNPM_META_FETCH_FAIL'),
    (200,{},b'{"large":"'+b'x'*100+b'"}',20,'ERR_PNPM_META_FETCH_FAIL'),
    (200,{'Content-Length':'30'},b'{}',100,'ERR_PNPM_META_FETCH_FAIL'),
])
def test_bounded_http_and_json_failures_remain_classifiable(status,headers,payload,limit,code):
    with registry(lambda path:(status,headers,payload)) as (url,requests):
        with pytest.raises(PackageQueryError) as failure:read_packument('fresh',url,max_bytes=limit,timeout_ms=500)
        assert failure.value.code==code


@pytest.mark.parametrize('version,requirement,expected',[
    ('1.0.0-alpha','*',False),('1.0.0-alpha','>=1.0.0-alpha <2',True),
    ('1.1.0-alpha','>=1.0.0-alpha <2',False),('1.2.0','^1.0.0',True),
    ('2.0.0-alpha','^1.0.0',False),('1.0.0-alpha','^1.0.0-alpha',True),
])
def test_registry_prerelease_selection_is_opt_in_per_comparator_core(version,requirement,expected):
    assert satisfies(version,requirement,include_prerelease=False) is expected


def test_redirect_rejects_non_http_or_https_downgrade():
    from urllib.request import Request
    redirects=RegistryRedirects();request=Request('https://example.invalid/metadata')
    for destination in ['file:///secret','http://example.invalid/metadata','https://user:secret@example.invalid/metadata']:
        with pytest.raises(PackageQueryError):redirects.redirect_request(request,None,302,'moved',{},destination)
