"""Compare native registry selection with real pinned Source pnpm queries."""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.boot.python_package_query import query_metadata,PackageQueryError
from dsh.boot.plugin_registry_policy import UNSPECIFIED

FIXTURE=None
FIELDS=['name','version','description','dsh','engines','peerDependencies']
CASES=[dict(name='latest',spec='fresh'),dict(name='tag',spec='fresh@next'),dict(name='exact',spec='fresh@1.0.0'),dict(name='v-prefix',spec='fresh@v1.0.0'),dict(name='range',spec='fresh@^1.0.0'),dict(name='star',spec='fresh@*'),dict(name='prerelease-range',spec='fresh@>=2.0.0-beta.1 <2.0.0'),dict(name='listing',spec='fresh',fields=['versions','time','dist-tags']),dict(name='missing-field',spec='fresh',fields=['unknown']),dict(name='scoped',spec='@scope/pkg@1.0.0'),dict(name='missing',spec='fresh@8.0.0')]
CASES += [dict(name='nested-field',spec='fresh',fields=['dsh.bundle.patch']),dict(name='alias',spec='alias@npm:@scope/pkg@^1.0.0'),dict(name='complete-time',spec='timed',fields=['versions','time','dist-tags']),dict(name='deprecated-latest',spec='deprecated@*'),dict(name='deprecated-range',spec='deprecated@^1.0.0'),dict(name='deprecated-exact',spec='deprecated@1.2.0'),dict(name='empty',spec='empty')]


class RegistryFixture:
    def __init__(self):
        self.requests=[];requests=self.requests
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(dict(path=self.path,authorization=self.headers.get('Authorization')))
                name=unquote(self.path).lstrip('/')
                versions={}
                for version in ['1.0.0','1.2.0','2.0.0-beta.1','2.0.0-beta.2','2.0.0']:
                    versions[version]=dict(name=name,version=version,description='fixture '+version,dsh=dict(bundle=dict(patch='patch.yml')),engines=dict(dsh='>=0.2.0'),dist=dict(tarball='https://example.invalid/plugin.tgz',integrity='sha512-fixture'))
                document=dict(name=name,versions=versions,time={'1.0.0':'2026-01-01T00:00:00.000Z'},**{'dist-tags':{'latest':'1.2.0','next':'2.0.0-beta.2'}})
                if name=='timed':document['time']={version:'2026-01-01T00:00:00.000Z' for version in versions}
                if name=='deprecated':versions['1.2.0']['deprecated']='retired'
                if name=='empty':document['versions']={}
                payload=json.dumps(document).encode('utf-8');self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)+'/'
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5);assert not self.thread.is_alive()


async def observe(workspace=None):
    fixture=FIXTURE if workspace is None else RegistryFixture();root=(workspace or WORKSPACE)/'native';root.mkdir(parents=True)
    blank=root/'npmrc';blank.write_text('',encoding='utf-8');rows=[]
    try:
        for case in CASES:
            try:result=query_metadata(str(root),case['spec'],case.get('fields',FIELDS),fixture.url,env=dict(NPM_CONFIG_USERCONFIG=str(blank)))
            except PackageQueryError as error:result=dict(error=error.code)
            rows.append(dict(name=case['name'],result={} if result is UNSPECIFIED else result))
        return rows
    finally:
        if workspace is not None:fixture.close()


def prepare(output):
    global FIXTURE,WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();FIXTURE=RegistryFixture();path=output/'input.json'
    path.write_text(json.dumps(dict(workspace=str(WORKSPACE),registry=FIXTURE.url,fields=FIELDS,cases=CASES)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_python_package_query.mts','Real pinned pnpm metadata selection over a loopback registry versus dependency-free Python: tags, exact versions, v prefix, ranges/prereleases, version/time/tag inventory, scoped names, absent fields and unavailable versions. No production backend promotion.',[Path(__file__).resolve(),ROOT/'dsh/boot/python_package_query.py',ROOT/'dsh/boot/semver.py'],prepare=prepare)
    finally:
        if FIXTURE is not None:
            FIXTURE.close();(WORKSPACE.parent/'registry-observations.json').write_text(json.dumps(FIXTURE.requests),encoding='utf-8')
