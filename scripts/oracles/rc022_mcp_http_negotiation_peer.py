"""Task-owned HTTP/SSE peer with append-only raw request observations."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    log=Path(sys.argv[1]);lock=threading.Lock();counts={};stopping=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def record(self,packet):
            with lock:
                with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(path=self.path,httpMethod=self.command,headers=dict(self.headers),packet=packet))+'\n')
        def answer(self,status,body,content='application/json',headers=None):
            self.send_response_only(status,'Fixture');self.send_header('content-type',content);self.send_header('content-length',str(len(body)));self.send_header('connection','close')
            for key,value in (headers or {}).items():self.send_header(key,value)
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError,OSError):pass
        def do_GET(self):self.record(None);self.answer(405,b'')
        def do_POST(self):
            packet=json.loads(self.rfile.read(int(self.headers['content-length'])));self.record(packet)
            mode=self.path.rsplit('/',1)[-1];method=packet.get('method');identity=packet.get('id')
            modern=mode.startswith('modern') or mode=='corrective'
            extra={}
            if method=='server/discover':
                with lock:count=counts.get(self.path,0)+1;counts[self.path]=count
                if mode in ('timeout','hold'):stopping.wait(5);return
                if mode in ('401','403','404','503'):self.answer(int(mode),b'controlled failure','text/plain');return
                if mode=='content':self.answer(200,b'controlled content','text/plain');return
                if mode=='malformed':self.answer(200,json.dumps(dict(jsonrpc='2.0',id=identity,result=None)).encode('utf-8'));return
                if mode=='corrective' and count==1:
                    error=dict(code=-32022,message='select modern',data=dict(supported=['2026-07-28']))
                    self.answer(400,json.dumps(dict(jsonrpc='2.0',id=identity,error=error)).encode('utf-8'));return
                if modern:result=dict(supportedVersions=['2026-07-28'],capabilities=dict(tools={},resources={}),instructions='Modern literal {{model}}',_meta={'io.modelcontextprotocol/serverInfo':dict(name='http-peer',version='1')})
                else:
                    self.answer(200,json.dumps(dict(jsonrpc='2.0',id=identity,error=dict(code=-32601,message='Method not found'))).encode('utf-8'));return
                extra['mcp-session-id']='discovery-must-not-set-session'
            elif method=='initialize':
                result=dict(protocolVersion='2025-11-25',capabilities=dict(tools={},resources={}),serverInfo=dict(name='http-peer',version='1'),instructions='Legacy literal {{model}}');extra['mcp-session-id']='fixture-session'
            elif identity is None:self.answer(202,b'');return
            elif method=='tools/list':result=dict(tools=[])
            elif method=='resources/read':result=dict(contents=[dict(uri=packet['params']['uri'],blob='YWJj')])
            else:self.answer(500,b'unexpected method');return
            if modern and method!='server/discover':result.update(resultType='complete',ttlMs=0,cacheScope='private')
            body=json.dumps(dict(jsonrpc='2.0',id=identity,result=result),ensure_ascii=True).encode('utf-8')
            if mode.endswith('-sse'):body=b'event: message\ndata: '+body+b'\n\n';content='text/event-stream'
            else:content='application/json'
            self.answer(200,body,content,extra)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.05),daemon=True);thread.start()
    print('http://127.0.0.1:'+str(server.server_address[1]),flush=True)
    try:sys.stdin.buffer.read()
    finally:stopping.set();server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
