"""Actual HTTP detail reads, bounded redirects/cancellation and CDN ordering."""
import asyncio
import gzip
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
SERVERS=None


class Servers:
    def __init__(self):
        self.requests=[];self.stop=threading.Event()
        state=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def handle(self):
                try:super().handle()
                except (ConnectionError,OSError):pass
            def do_GET(self):
                state.requests.append((self.server.server_port,self.path))
                try:
                    if self.path=='/headers':state.stop.wait(.3)
                    status,body,headers=200,b'ok',{}
                    if self.path=='/empty':body=b''
                    if self.path=='/missing':status=404
                    if self.path=='/denied':status=403
                    if self.path=='/declared':body=b'x';headers['content-length']='99'
                    if self.path=='/large':body=b'x'*30
                    if self.path=='/gzip':body=gzip.compress(b'decoded');headers['content-encoding']='gzip'
                    if self.path=='/gzip-large':body=gzip.compress(b'x'*1000);headers['content-encoding']='gzip'
                    if self.path in ('/redirect','/cross','/loop','/bare'):
                        status=302
                        if self.path!='/bare':headers['location']={'/redirect':'/ok','/cross':state.other+'/ok','/loop':'/loop'}[self.path]
                    if self.path in ('/body','/broken'):headers['content-length']='10'
                    headers.setdefault('content-length',str(len(body)))
                    self.send_response(status)
                    for name,value in headers.items():self.send_header(name,value)
                    self.end_headers()
                    if self.path=='/body':
                        self.wfile.write(b'x');self.wfile.flush();state.stop.wait(.3);body=b'x'*9
                    if self.path=='/broken':
                        self.wfile.write(b'x');self.wfile.flush();self.close_connection=True;return
                    self.wfile.write(body);self.wfile.flush()
                    if self.path=='/declared':self.close_connection=True
                except (OSError,ValueError):pass
        self.servers=[ThreadingHTTPServer(('127.0.0.1',0),Handler) for _ in range(2)]
        self.other='http://127.0.0.1:'+str(self.servers[1].server_port)
        self.url='http://127.0.0.1:'+str(self.servers[0].server_port)
        self.threads=[threading.Thread(target=server.serve_forever,daemon=True) for server in self.servers]
        for thread in self.threads:thread.start()
    def close(self):
        self.stop.set()
        for server in self.servers:server.shutdown();server.server_close()
        for thread in self.threads:thread.join()


def corpus():
    return ['ok','empty','missing','denied','declared','large','redirect','cross','loop','bare','headers','cancel','dispose','body','broken','gzip','gzip-large']


async def observe():
    from dsh.util.plugin_detail_http import fetch_body,NpmFiles
    from dsh.util.plugin_detail import DetailFailure
    from dsh.core.abort import AbortController
    owned=SERVERS is None;servers=Servers() if owned else SERVERS
    try:
        rows=[]
        for mode in corpus():
            signal,lifetime=AbortController(),AbortController()
            endpoint='headers' if mode in ('cancel','dispose') else mode
            timer=None
            if mode in ('cancel','dispose','body'):
                owner=lifetime if mode=='dispose' else signal
                timer=asyncio.get_running_loop().call_later(.07,owner.abort,RuntimeError('closed'))
            try:
                value=await fetch_body(servers.url+'/'+endpoint,40 if mode=='gzip' else 10,signal.signal,dict(timeoutMs=60 if mode=='headers' else 2000,lifetime=lifetime.signal))
                if value['ok']:value['bytes']=value['bytes'].decode('utf-8')
                result=dict(value=value)
            except DetailFailure as error:result=dict(error=error.reason)
            except Exception as error:result=dict(error=str(error))
            finally:
                if timer is not None:timer.cancel()
            rows.append(dict(name=mode,result=result))
        for mode in ('fallback','missing','too-large','all-down','cancelled','readme'):
            requests=[]
            async def fetch(url,max_bytes,signal,options):
                requests.append(url)
                if mode=='cancelled':raise RuntimeError('closed')
                if mode=='too-large':raise DetailFailure('too-large','limit')
                if mode=='missing':return dict(ok=False,status=404)
                if mode=='all-down':raise DetailFailure('network','offline')
                if len(requests)==1:return dict(ok=False,status=503)
                if mode=='readme' and not url.endswith('/readme.md'):return dict(ok=False,status=404)
                return dict(ok=True,bytes=b'document')
            files=NpmFiles('@scope/x','1.0.0',['jsdelivr','unpkg','npmmirror'],{},fetch)
            try:
                value=await files.readme('docs',100) if mode=='readme' else await files.read('docs/a b.md',100)
                if isinstance(value,bytes):value=value.decode('utf-8')
                if isinstance(value,dict):value=dict(path=value['path'],bytes=value['bytes'].decode('utf-8'))
                result=dict(value=value)
            except Exception as error:result=dict(error=getattr(error,'reason',str(error)))
            rows.append(dict(name='npm-'+mode,result=result,requests=requests))
        return rows
    finally:
        if owned:servers.close()


def prepare(output):
    global SERVERS
    SERVERS=Servers()
    path=output/'input.json';path.write_text(json.dumps(dict(url=SERVERS.url,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_detail_http.mts','Actual loopback HTTP on Source Fetch and Native owned transport: statuses, bounds, same-origin/blocked redirects, hop limits, timeout/caller/disposal cancellation, body cancellation, truncated and compressed bodies. CDN fallback, 404 terminal absence, non-network failures, cancellation and README name probing with controlled replies.',[Path(__file__).resolve(),ROOT/'dsh/util/plugin_detail_http.py',ROOT/'dsh/llm/http_stream.py'],prepare=prepare)
    finally:
        if SERVERS is not None:SERVERS.close()
