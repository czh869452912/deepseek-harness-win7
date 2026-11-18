"""Actual Session reporter HTTP exports against owned local collectors."""
import asyncio
import gzip
import json
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[dict(mode=mode,options={},env={}) for mode in ['ok','created','redirect','bad-request','server-error',
        'retry-once','retry-exhausted','retry-deadline','bad-json','truncated','oversized','timeout','reset-once']]
    rows += [dict(mode='ok',options=options,env={}) for options in [dict(compression='gzip'),
        dict(headers={'Authorization':'Bearer synthetic','X-Tenant':'fixture','Content-Type':'application/x-otlp'}),
        dict(userAgent='fixture-agent'),dict(headers={'User-Agent':'ignored'}),dict(concurrencyLimit=0)]]
    rows += [dict(mode=mode,options={},dynamic=True,env={}) for mode in ['ok','retry-once']]
    rows += [dict(mode='ok',options={},env=env) for env in [
        {'OTEL_EXPORTER_OTLP_HEADERS':'authorization=not-ours','OTEL_EXPORTER_OTLP_LOGS_HEADERS':'x-tenant=not-ours',
         'OTEL_EXPORTER_OTLP_ENDPOINT':'http://127.0.0.1:9','OTEL_EXPORTER_OTLP_LOGS_ENDPOINT':'http://127.0.0.1:9',
         'OTEL_EXPORTER_OTLP_CERTIFICATE':'not-a-certificate','OTEL_EXPORTER_OTLP_CLIENT_KEY':'not-a-key','HTTP_PROXY':'http://127.0.0.1:9'},
        {'OTEL_EXPORTER_OTLP_COMPRESSION':'gzip'},{'OTEL_EXPORTER_OTLP_LOGS_COMPRESSION':'none','OTEL_EXPORTER_OTLP_COMPRESSION':'gzip'},
        {'OTEL_EXPORTER_OTLP_TIMEOUT':'1000','OTEL_EXPORTER_OTLP_LOGS_TIMEOUT':'2000'}]]
    rows += [dict(mode=mode,options={},env={},agent=agent,tls=tls)
        for mode,agent,tls in [('ok','ca',True),('retry-once','ca',True),
            ('ok','insecure',True),('ok','identity',True),('retry-once','factory',True),
            ('retry-once','factory',False),('ok','factory-error',False),('ok','headers-error',False)]]
    values=[None,False,True,0,1,-1,1.5,2147483648,'1',{},[]]
    for field in ['timeoutMillis','compression','concurrencyLimit']:
        rows += [dict(mode='config',options={field:value},env={}) for value in values]
    for raw in ['', ' ', '0', '-1', '1.5','1000','0x10','0o10','0b10','1_000','Infinity','nan','gzip','none',' gzip ','bad']:
        for field in ['TIMEOUT','COMPRESSION']:
            rows.append(dict(mode='config',options={},env={
                'OTEL_EXPORTER_OTLP_LOGS_'+field:raw,'OTEL_EXPORTER_OTLP_'+field:'2000' if field=='TIMEOUT' else 'gzip'}))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8')
    (output/'localhost-cert.pem').write_bytes((ROOT/'tests/fixtures/tls/localhost-cert.pem').read_bytes())
    (output/'localhost-key.pem').write_bytes((ROOT/'tests/fixtures/tls/localhost-key.pem').read_bytes())
    return [path]


async def observe(entries=None, exporter_factory=None):
    from dsh.session.otel_session_channel_current import SessionLogReporter
    from dsh.session.otel_http_current import SessionHttpExporter,log_transport_options,resolve_headers
    from dsh.cordis.json_text import stringify_json
    from scripts.rc022_otel_wire_probe import cases as wire_cases
    record=wire_cases()[0]['records'][0];rows=[]
    for entry in cases() if entries is None else entries:
        if entry['mode']=='config':
            try:
                config=log_transport_options(entry['options'],entry['env'])
                config['headers']=await resolve_headers(entry['options'])
                rows.append(dict(value=json.loads(stringify_json(config))))
            except Exception as failure:rows.append(dict(error=str(failure)))
            continue
        hits=[];warnings=[];calls=[0];agent_calls=[];destroyed=[]
        loop=asyncio.get_running_loop()
        def cancel_after_request():
            nonlocal timer
            timer=loop.call_later(.03,controller.abort)
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('content-length','0')))
                if self.headers.get('content-encoding')=='gzip':body=gzip.decompress(body)
                selected=dict(contentType=self.headers.get('content-type'),authorization=self.headers.get('authorization'),
                    tenant=self.headers.get('x-tenant'),agent=self.headers.get('user-agent'),compression=self.headers.get('content-encoding'))
                hits.append(dict(document=json.loads(body),headers=selected))
                if entry.get('event'):selected['acceptEncoding']=self.headers.get('accept-encoding')
                mode=entry['mode'];attempt=len(hits)
                if entry.get('abort')=='delay' and attempt==1:
                    loop.call_soon_threadsafe(cancel_after_request)
                if mode=='reset-once' and attempt==1:
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                status=201 if mode=='created' else 302 if mode=='redirect' else 400 if mode=='bad-request' else 500 if mode=='server-error' else 503 if mode in ('retry-exhausted','retry-deadline') or mode=='retry-once' and attempt==1 else 200
                data=b'bad-json' if mode=='bad-json' else b'x'*4194305 if mode=='oversized' else b'{}'
                coding=entry.get('responseEncoding')
                if coding=='gzip':data=gzip.compress(data,mtime=0)
                if coding=='deflate':
                    import zlib
                    data=zlib.compress(data)
                if coding=='br':
                    import brotli
                    data=brotli.compress(data)
                if coding=='zstd':
                    import zstandard
                    data=zstandard.ZstdCompressor().compress(data)
                if mode=='timeout':time.sleep(.2)
                try:
                    self.send_response(status)
                    if coding:self.send_header('Content-Encoding',coding)
                    if status==302:self.send_header('Location','/redirected')
                    if status==503:self.send_header('Retry-After',entry.get('retryAfter','20' if mode=='retry-deadline' else '0'))
                    self.send_header('Content-Length','10' if mode=='truncated' else str(len(data)))
                    self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
                    if mode=='truncated':self.close_connection=True
                except (BrokenPipeError,ConnectionResetError,OSError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        cert=ROOT/'tests/fixtures/tls/localhost-cert.pem';key=ROOT/'tests/fixtures/tls/localhost-key.pem'
        if entry.get('tls'):
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(str(cert),str(key))
            server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01));thread.start()
        options=dict(url=('https://localhost:' if entry.get('tls') else 'http://127.0.0.1:')+str(server.server_port)+'/logs',**entry['options'])
        agent=entry.get('agent')
        if agent in ('ca','identity'):options['httpAgentOptions']={'ca':cert.read_text(encoding='utf-8')}
        if agent=='identity':options['httpAgentOptions'].update(cert=cert.read_text(encoding='utf-8'),key=key.read_text(encoding='utf-8'))
        if agent=='insecure':options['httpAgentOptions']={'rejectUnauthorized':False}
        if agent in ('factory','factory-error'):
            def factory(protocol):
                agent_calls.append(protocol)
                if agent=='factory-error':raise ConnectionResetError('synthetic callback failure')
                return SimpleNamespace(ssl_context=ssl.create_default_context(cafile=str(cert)) if protocol=='https:' else None,
                    destroy=lambda:destroyed.append(True))
            options['httpAgentOptions']=factory
        if agent=='headers-error':
            def failed_headers():raise ConnectionResetError('synthetic callback failure')
            options['headers']=failed_headers
        if entry['mode'] in ('timeout','retry-deadline'):options['timeoutMillis']=50
        if entry.get('abort')=='delay':options['timeoutMillis']=1000
        if entry.get('dynamic'):
            async def headers():calls[0]+=1;return {'Authorization':'Bearer synthetic-'+str(calls[0])}
            options['headers']=headers
        environment=dict(os.environ)
        for name in ['OTEL_EXPORTER_OTLP_TIMEOUT','OTEL_EXPORTER_OTLP_LOGS_TIMEOUT','OTEL_EXPORTER_OTLP_COMPRESSION','OTEL_EXPORTER_OTLP_LOGS_COMPRESSION']:
            environment.pop(name,None)
        environment.update(entry['env'])
        previous={key:os.environ.get(key) for key in entry['env']}
        os.environ.update(entry['env'])
        extra={};timer=None
        if entry.get('event'):
            from dsh.core.abort import AbortController
            controller=AbortController();extra['signal']=controller.signal
            if entry.get('abort')=='before':controller.abort()
        exporter=(exporter_factory or SessionHttpExporter)(options,environment=environment,**extra)
        reporter=SessionLogReporter(dict(scope=dict(name='fixture',version='1'),resourceAttributes={},
            onFailure=lambda message,error=None:warnings.append(dict(message=message,error=None if error is None else str(error)))),exporter)
        try:reporter.reportSessionLog(record);await reporter.shutdown()
        finally:
            await exporter.shutdown()
            if timer is not None:timer.cancel()
            await asyncio.get_running_loop().run_in_executor(None,server.shutdown);server.server_close();thread.join()
            for key,value in previous.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
        rows.append(dict(hits=hits,warnings=warnings,headerCalls=calls[0],agentCalls=agent_calls,agentDestroyed=len(destroyed)))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_otel_http.mts','Actual Session reporter/exporter HTTP: channel headers/identity, compression, status retry, response limits, truncation and timeout; dynamic per-attempt headers and isolated collector environment.',
        [Path(__file__).resolve(),ROOT/'dsh/session/otel_http_current.py',ROOT/'dsh/llm/http_stream.py'],prepare=prepare)
