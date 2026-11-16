import asyncio
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dsh.cordis.context import Context
from dsh.host.http_proxy import install_proxy_from_environment
from dsh.host.http_proxy_policy import PROXY_ENV_NAMES
from dsh.web.http_fetch_current import CurrentWebFetchHttp, DEFAULTS
from dsh.web.web_service_current import CurrentWebService
from dsh.web.tool_web.fetch import render_fetch_output
from scripts.oracles.http_proxy_current_python import Lookup
from scripts.rc022_http_fetch_probe import observe


@pytest.mark.asyncio
async def test_real_http_fixed_source_corpus(tmp_path):
    rows = await observe()
    (tmp_path/'http-fetch-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows) == 140
    # Unchanged 38a6a5c Source, qualified by rc022-http-fetch-paired6.
    encoded = json.dumps(rows,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('utf-8')
    assert hashlib.sha256(encoded).hexdigest() == 'a56aef0810d5fe48ce0c78f2557ea96b09c4ca0ba3227640b7aedaaf6364ef63'


@pytest.mark.asyncio
async def test_canonical_plugin_proxy_loopback_raw_html_and_owned_disposal(monkeypatch):
    for name in PROXY_ENV_NAMES: monkeypatch.delenv(name, raising=False)
    hits = []; changes = []; raw = b'<h1>Page</h1><p>body</p>'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            hits.append(dict(path=self.path,proxy=self.headers.get('proxy-authorization'),cookie=self.headers.get('cookie'),
                             auth=self.headers.get('authorization'),agent=self.headers.get('user-agent')))
            self.send_response(200); self.send_header('content-type','text/html'); self.send_header('content-length',str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));thread.start()
    dispose=await install_proxy_from_environment(Lookup({'HTTP_PROXY':'http://user:pass@127.0.0.1:'+str(server.server_port)}),lambda _:None)
    ctx=Context();ctx.on('web/providers-changed',lambda:changes.append('changed'))
    try:
        await ctx.plugin(CurrentWebService,dict(fetchProvider='http'))
        owner=await ctx.plugin(CurrentWebFetchHttp)
        assert ctx.web.listProviders()['fetch'][0]['id']=='http'
        assert owner.effectiveConfig==DEFAULTS
        result=await ctx.web.fetch(dict(url='http://fetch.fixture.test/page'))
        assert result['body']==dict(kind='html',content=raw.decode('utf-8'))
        rendered=render_fetch_output(result,10000)
        assert '<h1>' not in json.dumps(rendered) and 'Page' in json.dumps(rendered)
        await ctx.web.fetch(dict(url='http://127.0.0.1:'+str(server.server_port)+'/local'))
        assert [hit['path'] for hit in hits]==['http://fetch.fixture.test/page','/local']
        assert [hit['proxy'] for hit in hits]==['Basic dXNlcjpwYXNz',None]
        assert all(hit['cookie'] is None and hit['auth'] is None and hit['agent']==DEFAULTS['userAgent'] for hit in hits)
        await owner.dispose()
        for _ in range(5): await asyncio.sleep(0)
        assert ctx.web.listProviders()['fetch']==[] and changes==['changed','changed']
    finally:
        await ctx.fiber.dispose();await dispose()
        server.shutdown();server.server_close();thread.join(2)
