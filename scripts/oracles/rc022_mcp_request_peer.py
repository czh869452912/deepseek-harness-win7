"""Owned localhost HTTP/SSE peer for per-request deadlines and cancellation."""
import json,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path


def main():
    log=Path(sys.argv[1]);lock=threading.Lock();stopping=threading.Event();counts={}
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):self.send_response(405);self.send_header('Content-Length','0');self.end_headers()
        def do_DELETE(self):self.send_response(204);self.end_headers()
        def answer(self,value,status=None):
            body=json.dumps(value,separators=(',',':')).encode('utf-8') if value is not None else b''
            self.send_response(status if status is not None else (200 if value is not None else 202))
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers()
            self.wfile.write(body);self.wfile.flush()
        def do_POST(self):
            try:self.handle_packet()
            except (ConnectionError,OSError):pass
        def handle_packet(self):
            packet=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            with lock:
                with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(path=self.path,packet=packet,headers={key.lower():value for key,value in self.headers.items()}))+'\n')
                key=(self.path,packet['method']);counts[key]=counts.get(key,0)+1;count=counts[key]
            mode=self.path.rsplit('/',1)[-1];modern=mode.startswith('modern');method=packet['method']
            if method=='server/discover':
                if not modern:self.answer(dict(jsonrpc='2.0',id=packet['id'],error=dict(code=-32601,message='legacy')));return
                result=dict(supportedVersions=['2026-07-28'],capabilities=dict(tools={}))
            elif method=='initialize':result=dict(protocolVersion='2025-11-25',capabilities=dict(tools={}),serverInfo=dict(name='request-peer',version='1'))
            elif 'id' not in packet:self.answer(None);return
            elif method=='tools/list':
                if 'header' in mode:
                    if mode.endswith('refreshbad') and count>1:
                        self.answer(dict(jsonrpc='2.0',id=packet['id'],error=dict(code=-32603,message='refresh failed')));return
                    header='Trace' if count==1 else 'Next'
                    result=dict(tools=[dict(name='probe',inputSchema=dict(type='object',properties=dict(trace={'type':'string','x-mcp-header':header}))),
                        dict(name='invalid',inputSchema=dict(type='object',items={'type':'string','x-mcp-header':'Forbidden'}))])
                    if mode.endswith('schema'):
                        result['tools'][0]['outputSchema']=dict(type='object',properties=dict(answer=dict(type='number' if count==1 else 'string')),required=['answer'])
                    elif mode.endswith('compilebad') and count>1:
                        result['tools'][0]['outputSchema']={'$schema':'https://invalid.example/schema','type':'object'}
                elif 'hold' in mode or (mode.endswith('overlap') and packet.get('params',{}).get('hold')):
                    stopping.wait(1);result=dict(tools=[])
                elif 'error' in mode:
                    error=dict(code=-32602,message='serve-failed')
                    if mode.endswith('null'):error['data']=None
                    elif mode.endswith('object'):error['data']=dict(detail='retained')
                    self.answer(dict(jsonrpc='2.0',id=packet['id'],error=error));return
                elif 'progress' in mode:
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers();self.close_connection=True
                    for index in range(1,4):
                        if stopping.wait(.1):return
                        self.wfile.write(('event: message\ndata: '+json.dumps(dict(jsonrpc='2.0',method='notifications/progress',params=dict(progressToken=packet['params']['_meta']['progressToken'],progress=index,message='step'+str(index))))+'\n\n').encode());self.wfile.flush()
                    stopping.wait(.05)
                    result=dict(tools=[])
                    if modern:result.update(resultType='complete',ttlMs=0,cacheScope='private')
                    self.wfile.write(('event: message\ndata: '+json.dumps(dict(jsonrpc='2.0',id=packet['id'],result=result))+'\n\n').encode());self.wfile.flush();return
                else:
                    stopping.wait(.03);result=dict(tools=[])
                if modern:result.update(resultType='complete',ttlMs=0,cacheScope='private')
            elif method=='tools/call' and 'header' in mode:
                if mode.endswith('always') or (count==1 and not mode.endswith('success')):
                    self.answer(dict(jsonrpc='2.0',id=packet['id'],error=dict(code=-32020,message='headers stale',data=dict(stale=True))),400 if modern else 200);return
                result=dict(content=[dict(type='text',text='called')])
                if mode.endswith('schema'):result['structuredContent']=dict(answer='accepted')
                if modern:result['resultType']='complete'
            else:self.answer(dict(jsonrpc='2.0',id=packet['id'],error=dict(code=-32601,message='unknown')));return
            self.answer(dict(jsonrpc='2.0',id=packet['id'],result=result))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.02),daemon=True);thread.start()
    print('http://127.0.0.1:'+str(server.server_port),flush=True)
    try:sys.stdin.buffer.read()
    finally:stopping.set();server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
