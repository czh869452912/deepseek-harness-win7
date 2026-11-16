"""Actual loopback HTTP exchange for the pinned model listing reader."""
import asyncio
import gzip
import json
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

CASES=['success','override','case-append','gzip','deflate','deflate-raw','broken-gzip','status','invalid-json','invalid-listing','redirect','header-timeout','body-timeout','abort','pre-abort']
BODY=b'{"data":[{"id":"a","api_capabilities":{"anthropic_messages":{}}}]}'


async def observe():
    from dsh import __version__
    from dsh.core.abort import AbortController
    from dsh.core.timeout import deadline
    from dsh.llm.model_listing import requestModelListing,LISTING_TIMEOUT
    hits=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_): pass
        def do_GET(self):
            hits.append(dict(path=self.path,auth=self.headers.get('x-api-key'),accept=self.headers.get('accept'),ua=self.headers.get('user-agent')))
            try:
                if self.path in ('/header-timeout','/abort'): time.sleep(.15)
                payload=b'not-json' if self.path in ('/invalid-json','/status') else b'{}' if self.path=='/invalid-listing' else BODY
                encoding=None
                if self.path in ('/gzip','/broken-gzip'):
                    payload=gzip.compress(payload);encoding='gzip'
                    if self.path=='/broken-gzip': payload=payload[:-5]
                if self.path in ('/deflate','/deflate-raw'):
                    payload=zlib.compress(payload);encoding='deflate'
                    if self.path=='/deflate-raw': payload=payload[2:-4]
                self.send_response(401 if self.path=='/status' else 302 if self.path=='/redirect' else 200)
                if encoding is not None: self.send_header('Content-Encoding',encoding)
                if self.path=='/redirect': self.send_header('Location','/leaked')
                self.send_header('Content-Length',str(len(payload)));self.end_headers()
                if self.path=='/body-timeout':
                    self.wfile.write(payload[:1]);self.wfile.flush();time.sleep(.15);payload=payload[1:]
                self.wfile.write(payload);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,name='listing-http-probe');thread.start()
    root='http://127.0.0.1:'+str(server.server_port)
    rows=[]
    try:
        for name in CASES:
            parent=AbortController();limit=deadline(parent.signal,80 if 'timeout' in name else 2000,LISTING_TIMEOUT)
            timer=None
            if name=='pre-abort': parent.abort(RuntimeError('caller'))
            if name=='abort': timer=asyncio.get_running_loop().call_later(.04,parent.abort)
            headers={'x-api-key':'test-secret'}
            if name=='override': headers.update({'accept':'custom/type','user-agent':'custom/1'})
            if name=='case-append': headers.update({'Accept':'custom/type','User-Agent':'custom/1'})
            before=len(hits)
            try: result=dict(value=await requestModelListing(root+'/'+name,headers,limit.signal))
            except Exception as error:
                result=dict(error=getattr(error,'message',str(error)).replace(root,'<origin>'),code=getattr(error,'code',None),status=getattr(error,'failure',{}).get('status'))
            finally:
                limit.dispose()
                if timer is not None: timer.cancel()
            requests=hits[before:]
            for hit in requests:
                if hit['ua']!='custom/1':
                    extra=', custom/1' if name=='case-append' else ''
                    assert hit['ua']=='deepseek-harness/'+__version__+' (+https://github.com/deepseek-ai/deepseek-harness)'+extra
                    hit['ua']='<active-runtime-attribution>'+extra
            rows.append(dict(name=name,requests=requests,**result))
        return rows
    finally:
        server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_listing_http.mts','Actual original/native loopback HTTP: authenticated GET and attribution/default header override, '
        'non-2xx after full body, invalid JSON/listing, redirect refusal without a target request, deadline before headers and during body, '
        'caller abort and pre-abort. Dynamic origin and each independently verified active runtime attribution are explicitly marked.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/model_listing.py',ROOT/'dsh/llm/http_stream.py',ROOT/'dsh/llm/attribution.py'])
