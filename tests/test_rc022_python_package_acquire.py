import copy
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import ssl
import tarfile
import threading
from urllib.parse import urlsplit

import pytest

from dsh.boot.python_package_acquire import acquired_registry_package,NativePackageRefused
from dsh.boot import python_plugins as store
from dsh.boot.profile_boot import INSTALL_ANCHOR
from test_rc022_python_package_tarball import archive,sri
from test_python_plugin_distribution import profile,boot,close,echo,EXAMPLE,PACKAGE


@pytest.fixture
def registry_package(tmp_path,monkeypatch):
    certificate=Path(__file__).parent/'fixtures/tls/localhost-cert.pem';context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(str(certificate),str(certificate.with_name('localhost-key.pem')))
    monkeypatch.setattr(ssl,'_create_default_https_context',lambda:ssl.create_default_context(cafile=str(certificate)))
    original=json.loads((EXAMPLE/'package.json').read_text(encoding='utf-8'));state=dict(metadata=copy.deepcopy(original),requests=[],files={name:(EXAMPLE/name).read_bytes() for name in original['dsh']['release']['files']})
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path;state['requests'].append(path)
            if path=='/archive.tgz':payload=state['payload']
            else:
                version=state.get('index_version',original['version']);metadata=dict(state['metadata'],dist=dict(tarball=state['url']+'/archive.tgz?token=fixture-secret',integrity=state.get('integrity',sri(state['payload']))))
                payload=json.dumps(dict(name=state.get('root_name',PACKAGE),versions={version:metadata},**{'dist-tags':{'latest':version}})).encode('utf-8')
            self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers()
            if path=='/archive.tgz' and 'pause' in state:
                state['entered'].set();state['pause'].wait(5)
            try:self.wfile.write(payload)
            except OSError:pass
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.socket=context.wrap_socket(server.socket,server_side=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();state['url']='https://localhost:'+str(server.server_port)
    def pack(manifest=None):
        files=dict(state['files']);files['package.json']=json.dumps(manifest or original).encode('utf-8')
        path=tmp_path/'package.tgz';archive(path,[('package/'+name,payload,tarfile.REGTYPE) for name,payload in files.items()]);state['payload']=path.read_bytes()
    state['pack']=pack;pack()
    blank=tmp_path/'npmrc';blank.write_text('',encoding='utf-8');state['env']=dict(NPM_CONFIG_USERCONFIG=str(blank),NO_PROXY='localhost,127.0.0.1')
    try:yield state
    finally:server.shutdown();server.server_close();worker.join(timeout=5);assert not worker.is_alive()


@pytest.mark.asyncio
async def test_registry_metadata_binds_actual_archive_and_native_boot(profile,registry_package):
    home,directory=profile;state=registry_package;before=(directory/'package.json').read_bytes()
    with acquired_registry_package(str(directory),PACKAGE,state['url'],state['env']) as candidate:
        assert (directory/'package.json').read_bytes()==before
        assert candidate.manifest['name']==PACKAGE and candidate.manifest['version']=='0.1.0'
        assert candidate.acquisition['url']==state['url']+'/archive.tgz'
        source=Path(candidate.source);assert source.is_file()
        assert store.install(str(directory),str(source),INSTALL_ANCHOR,candidate.acquisition)==PACKAGE
    assert not source.exists()
    assert state['requests']==['/@example%2Fpython-echo','/archive.tgz']
    result=await boot(home)
    try:assert await echo(result['ctx'])=='Python echo: hello'
    finally:await close(result)
    store.uninstall(str(directory),PACKAGE)


@pytest.mark.parametrize('failure,fetch_archive',[
    ('metadata-name',False),('metadata-version',False),('metadata-abi',False),('metadata-api',False),('metadata-engines',False),
    ('weak-integrity',False),('wrong-integrity',True),('archive-name',True),('archive-version',True),
    ('archive-engines',True),('archive-syntax',True),('unlisted-file',True),
])
def test_refusals_never_mutate_profile_or_import_plugin(profile,registry_package,failure,fetch_archive):
    home,directory=profile;state=registry_package;before=(directory/'package.json').read_bytes();manifest=copy.deepcopy(state['metadata'])
    if failure=='metadata-name':state['root_name']='@example/other'
    if failure=='metadata-version':state['metadata']['version']='2.0.0'
    if failure=='metadata-abi':state['metadata']['dsh'].pop('python')
    if failure=='metadata-api':state['metadata']['dsh']['python']['apiVersion']=2
    if failure=='metadata-engines':state['metadata']['engines']=dict(dsh='>=99.0.0')
    if failure=='weak-integrity':state['integrity']=sri(state['payload'],'sha1')
    if failure=='wrong-integrity':state['integrity']=sri(b'other')
    if failure=='archive-name':manifest['name']='@example/other';state['pack'](manifest)
    if failure=='archive-version':manifest['version']='2.0.0';state['pack'](manifest)
    if failure=='archive-engines':manifest['engines']=dict(dsh='>=99.0.0');state['pack'](manifest)
    if failure=='archive-syntax':state['files']['python/echo/plugin.py']=b'def broken(:';state['pack']()
    if failure=='unlisted-file':state['files']['unlisted.txt']=b'extra';state['pack']()
    with pytest.raises(ValueError):
        with acquired_registry_package(str(directory),PACKAGE+'@0.1.0',state['url'],state['env']):pytest.fail('invalid candidate was admitted')
    assert ('/archive.tgz' in state['requests']) is fetch_archive
    assert (directory/'package.json').read_bytes()==before
    assert not (directory/'node_modules/@example/python-echo').exists()
    assert not (directory/store.STAGING).exists() and not (directory/store.JOURNAL).exists()


def test_exact_version_exemption_is_applied_to_metadata_and_archive(profile,registry_package):
    from dsh.boot.plugin_compatibility import get_dsh_runtime_version
    home,directory=profile;state=registry_package;state['metadata']['engines']=dict(dsh='>=99.0.0');state['pack'](state['metadata'])
    exemptions={PACKAGE+'@0.1.0':[get_dsh_runtime_version()]}
    with acquired_registry_package(str(directory),PACKAGE,state['url'],state['env'],exemptions) as candidate:assert candidate.manifest['version']=='0.1.0'
    assert '/archive.tgz' in state['requests']


def test_native_registry_mutation_rejects_alias_before_http(profile,registry_package):
    home,directory=profile;state=registry_package
    with pytest.raises(NativePackageRefused,match='own name'):
        with acquired_registry_package(str(directory),'alias@npm:'+PACKAGE,state['url'],state['env']):pytest.fail('alias admitted')
    assert state['requests']==[]
