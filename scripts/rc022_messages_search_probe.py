"""Real Messages search, operation-bound auth and cancellation against fixed Source."""
import asyncio
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

ANSWER=dict(content=[dict(type='text',citations=[dict(url='https://page.test',cited_text='first citation')]),
    dict(type='web_search_tool_result',content=[dict(type='web_search_result',url='https://page.test',title='Page',page_age='today'),
        dict(type='web_search_result',url='https://page.test',title='duplicate')])])


def cases():
    rows=[dict(account=account,key=key,mode='ok') for account in (None,'token','empty','error','type-error')
          for key in (None,'literal','empty','ref','ref-empty','ref-error','ref-type-error')]
    for account in (None,'token'):
        rows += [dict(account=account,key='ref',mode=mode) for mode in ('unauthorized','unauthorized-removal-error',
            'unauthorized-reject-abort','error-string','error-object','error-fallback','error-invalid','no-results','invalid-json',
            'redirect','pre-abort','header-abort','body-abort','unauthorized-body-abort','dropped-body','record-error')]
    rows += [dict(account=account,key='literal',mode=mode) for account in ('held',None)
             for mode in ('resolve-abort','resolve-reject-late','snapshot') if account is not None or mode=='snapshot']
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return[path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.web.messages_search_current import DeepSeekSearchProvider,DEFAULTS
    inputs=cases();hits=[];entered=threading.Event();rows=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_):pass
        def do_POST(self):
            try:self.respond()
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):self.close_connection=True
        def respond(self):
            index=int(self.path.split('/')[1]);mode=inputs[index]['mode']
            body=json.loads(self.rfile.read(int(self.headers['content-length'])))
            headers={key:self.headers[key] for key in ('x-dsh-auth-token','x-api-key','authorization','anthropic-version','content-type','accept','user-agent') if key in self.headers}
            hits.append(dict(path=self.path,headers=headers,body=body));entered.set()
            if mode=='header-abort':return self.hold()
            status=401 if mode.startswith('unauthorized') else 503 if mode.startswith('error-') else 302 if mode=='redirect' else 200
            payload=ANSWER
            if mode=='no-results':payload=dict(content=[])
            elif mode=='error-string':payload=dict(error='detail')
            elif mode=='error-object':payload=dict(error=dict(message='detail'))
            elif mode=='error-fallback':payload=dict(error=dict(message=None),message='fallback-detail')
            elif mode.startswith('unauthorized'):payload=dict(error=dict(message='rejected'))
            data=b'invalid' if mode in ('invalid-json','error-invalid') else json.dumps(payload).encode('utf-8')
            self.send_response(status);self.send_header('content-type','application/json');self.send_header('content-length',str(len(data)))
            if status==302:self.send_header('location','/must-not-follow')
            self.end_headers()
            if 'body-abort' in mode or mode=='dropped-body':
                self.wfile.write(data[:1]);self.wfile.flush()
                if mode=='dropped-body':self.close_connection=True;return
                return self.hold()
            self.wfile.write(data)
        def hold(self):
            self.connection.settimeout(2)
            try:self.connection.recv(1)
            except OSError:pass
            self.close_connection=True
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=False
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));thread.start()
    origin='http://127.0.0.1:'+str(server.server_port)
    def fail(message,typed=False):raise TypeError(message) if typed else RuntimeError(message)
    try:
        rows.append(dict(description=DeepSeekSearchProvider(lambda:DEFAULTS).description))
        for index,entry in enumerate(inputs):
            mode=entry['mode'];events=[];records=[];reads=[];start=len(hits);entered.clear();controller=AbortController()
            pending=asyncio.get_running_loop().create_future()
            async def resolve(tag,endpoint=None):
                events.append(('account:'+endpoint.replace(origin,'<origin>')) if endpoint else 'key')
                if tag=='held':return await pending
                if tag.endswith('error'):fail('read-failed',tag.endswith('type-error'))
                return None if tag.endswith('empty') else 'account-token' if endpoint else 'api-key'
            async def reject(token):
                events.append('reject:'+token)
                if mode=='unauthorized-removal-error':fail('remove-failed')
                if mode=='unauthorized-reject-abort':controller.abort(RuntimeError('rejected grant'))
            def record(request):
                records.append(request)
                if mode=='record-error':fail('record-failed')
            current=dict(DEFAULTS,baseURL=origin+'/'+str(index),recordRequest=record)
            if entry['account'] is not None:current.update(resolveAccountToken=lambda endpoint:resolve(entry['account'],endpoint),rejectAccountToken=reject)
            if entry['key'] in ('literal','empty'):current['apiKey']='literal-key' if entry['key']=='literal' else ''
            elif entry['key'] is not None:current['resolveApiKey']=lambda:resolve(entry['key'])
            def options():reads.append('read');return current
            provider=DeepSeekSearchProvider(options);available=provider.available()
            if mode=='pre-abort':controller.abort(RuntimeError('caller cancelled'))
            request=dict(query='fixture');operation=provider.search(request,controller.signal)
            if mode.startswith('resolve-') or mode=='snapshot' and entry['account']=='held':
                while not events:await asyncio.sleep(0)
                if mode.startswith('resolve-'):
                    controller.abort(RuntimeError('caller cancelled'));await asyncio.sleep(0)
                    if mode=='resolve-reject-late':pending.set_exception(RuntimeError('late-failed'))
                    else:pending.set_result('late-token')
                else:
                    current=dict(DEFAULTS,baseURL='https://must-not-use.invalid',apiKey='changed-key')
                    request['query']='changed-query';pending.set_result('captured-token')
            elif mode=='snapshot':request['query']='changed-query'
            elif mode in ('header-abort','body-abort','unauthorized-body-abort'):
                while not entered.is_set():await asyncio.sleep(.02)
                await asyncio.sleep(.03);controller.abort(RuntimeError('caller cancelled'))
            try:result=dict(value=await operation)
            except Exception as error:
                message=getattr(error,'message',str(error)).replace(origin,'<origin>')
                if mode=='invalid-json':message=re.sub(r'(?s)(unprocessable response body: ).*?(\n\nThe web request)',r'\1<runtime JSON diagnostic>\2',message)
                result=dict(code=getattr(error,'code',None),message=message)
            controller.abort(RuntimeError('scope disposed'))
            for _ in range(3):await asyncio.sleep(0)
            rows.append(json.loads(json.dumps(dict(available=available,reads=len(reads),result=result,events=events,
                records=records,hits=hits[start:],listeners=len(controller.signal._listeners))).replace(origin,'<origin>')))
        return rows
    finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_messages_search.mts','Actual native Messages search and bound account/API credentials, 401, request recording and cancellation.',
        [Path(__file__).resolve(),ROOT/'dsh/web/messages_search_current.py',ROOT/'dsh/host/http_request.py'],prepare=prepare)
