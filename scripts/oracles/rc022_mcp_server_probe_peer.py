"""Owned loopback MCP probe peer; no external network or user credentials."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    log = Path(sys.argv[1]); lock = threading.Lock(); stopping = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def answer(self, packet):
            body = json.dumps(packet).encode('utf-8') if packet is not None else b''
            self.send_response_only(200 if packet is not None else 202)
            self.send_header('content-type','application/json');self.send_header('content-length',str(len(body)));self.send_header('connection','close');self.end_headers()
            try:self.wfile.write(body)
            except OSError:pass
        def do_GET(self):
            self.send_response_only(405);self.send_header('content-length','0');self.end_headers()
        def do_POST(self):
            packet = json.loads(self.rfile.read(int(self.headers['content-length'])))
            with lock:
                with log.open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(dict(path=self.path,packet=packet,authorization=self.headers.get('Authorization')))+'\n')
            mode = self.path.rsplit('/',1)[-1];method = packet['method'];modern = mode.startswith('modern')
            capabilities = {} if mode=='none' else dict(tools={})
            if method=='server/discover':
                if modern:
                    result = dict(supportedVersions=['2026-07-28'],capabilities=capabilities,_meta={'io.modelcontextprotocol/serverInfo':dict(name='inspection-peer',version='1',extra='drop')})
                else:
                    self.answer(dict(jsonrpc='2.0',id=packet['id'],error=dict(code=-32601,message='legacy')));return
            elif method=='initialize':
                result = dict(protocolVersion='2025-11-25',capabilities=capabilities,serverInfo=dict(name='inspection-peer',version='1',extra='drop'))
            elif 'id' not in packet:
                self.answer(None);return
            elif method=='tools/list':
                if mode=='hold':stopping.wait(5);return
                cursor = packet.get('params',{}).get('cursor')
                names = ['a','b'] if cursor is None else ['c']
                result = dict(tools=[dict(name=name,inputSchema=dict(type='object')) for name in names])
                if mode in ('loop','modern-loop'):result['nextCursor']='again'
                elif cursor is None:result['nextCursor']='next'
                if modern:result.update(resultType='complete',ttlMs=0,cacheScope='private')
                if mode=='modern-cache':result['ttlMs']=60000
                if mode=='modern-output':
                    for tool in result['tools']:
                        tool['outputSchema']=dict(type='object',properties=dict(answer=dict(type='integer')),required=['answer'])
                if mode=='modern-input-state':result=dict(resultType='input_required',requestState='opaque')
                elif mode=='modern-input-empty':result=dict(resultType='input_required')
                elif mode=='modern-unknown-result':result=dict(resultType='future')
                elif mode=='modern-invalid-tools':result=dict(resultType='complete',tools='invalid',ttlMs=0,cacheScope='private')
                elif mode=='modern-missing-result-type':result=dict(tools=[])
                elif mode in ('modern-state-once', 'modern-state-empty'):
                    state = '' if mode=='modern-state-empty' else 'opaque\x00state'
                    result = (dict(resultType='complete',tools=[],ttlMs=0,cacheScope='private')
                        if packet.get('params',{}).get('requestState')==state else dict(resultType='input_required',requestState=state))
                elif mode.startswith('modern-input-entry-'):
                    label=mode[len('modern-input-entry-'):]
                    entry={'malformed':'bad','nonstring':dict(method=3),'unknown':dict(method='future/request'),
                        'roots':dict(method='roots/list'),'sampling':dict(method='sampling/createMessage'),
                        'elicitation':dict(method='elicitation/create')}[label]
                    result=dict(resultType='input_required',inputRequests=dict(query=entry))
            elif method=='tools/call' and mode=='modern-output':
                result=dict(resultType='complete',content=[],structuredContent=packet['params'].get('arguments',{}))
            else:
                self.answer(dict(jsonrpc='2.0',id=packet.get('id'),error=dict(code=-32601,message='unknown')));return
            self.answer(dict(jsonrpc='2.0',id=packet['id'],result=result))
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread = threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.05),daemon=True);thread.start()
    print('http://127.0.0.1:'+str(server.server_address[1]),flush=True)
    try:sys.stdin.buffer.read()
    finally:stopping.set();server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
