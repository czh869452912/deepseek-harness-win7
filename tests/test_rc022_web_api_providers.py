import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dsh.core.abort import AbortController
from dsh.web.deepseek_api_providers import DeepSeekSearchApiProvider, DeepSeekFetchApiProvider
from dsh.web.web_service import WebError
from scripts.rc022_web_api_provider_probe import observe


@pytest.mark.asyncio
async def test_projection_snapshot_availability_and_inclusive_window_corpus():
    rows = await observe()
    assert len(rows) == 293
    rates = [row['result'] for row in rows if row['kind'] == 'rate']
    assert [row['waits'] for row in rates] == [[2], [1], [], [1]]
    assert rates[-1]['code'] == 'WEB_ABORTED'
    failures = [row['result'] for row in rows if row['kind'] == 'snapshot-error']
    assert failures == [dict(returned=True, message='snapshot-failed'), dict(returned=False, message='snapshot-failed')]
    assert set(rows[-1]['search']) == set(rows[-1]['fetch']) == {'en', 'zh', 'ja', 'es', 'fr', 'de', 'ru', 'pt'}


@pytest.mark.asyncio
async def test_real_http_payloads_and_cancelled_waiter_do_not_consume_an_admission():
    hits = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['content-length'])))
            hits.append(dict(path=self.path, payload=payload, time=time.monotonic(), key=self.headers.get('authorization')))
            body = dict(content='# Page\n\nMarkdown') if self.path.endswith('/fetch') else dict(results=[
                dict(url='https://page.test', title='Page', snippet='snippet', summary='summary', date=None)])
            data = json.dumps(body).encode('utf-8')
            self.send_response(200); self.send_header('content-length', str(len(data))); self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), name='web-api-provider-test'); thread.start()
    options = dict(auth={'sources': [dict(kind='api-key', baseURL='http://127.0.0.1:'+str(server.server_port)+'/tools/', key='fixture-key')]},
                   count=10, requestsPerSecond=1, originalQuestion=lambda: 'first\n question',
                   guidance=dict(subject='Search', plugin='web-deepseek-api', custom=True,
                                 baseURLField='searchBaseURL', apiKeyEnvField='searchApiKeyEnv'))
    pending = None; controller = AbortController()
    try:
        search = DeepSeekSearchApiProvider(lambda: options); fetch = DeepSeekFetchApiProvider(lambda: options)
        first = search.search(dict(query='first', maxResults=3))
        options = dict(options, count=7, originalQuestion=lambda: 'second question')
        result = await first
        assert result['sources'][0]['summary'] == 'summary'
        assert hits[0]['payload'] == dict(query='first', count=3, need_content=False, ori_question='first question')
        pending = search.search(dict(query='must-not-send'), controller.signal)
        await asyncio.sleep(0)
        controller.abort(RuntimeError('cancel-waiter'))
        with pytest.raises(WebError) as caught: await pending
        assert caught.value.code == 'WEB_ABORTED' and len(hits) == 1
        assert not controller.signal._listeners
        await search.search(dict(query='next'))
        assert hits[1]['time']-hits[0]['time'] >= .95
        assert hits[1]['payload']['count'] == 7 and hits[1]['payload']['ori_question'] == 'second question'
        page = await fetch.fetch(dict(url='https://page.test/article'))
        assert page == dict(url='https://page.test/article', statusCode=200, body=dict(kind='text', content='# Page\n\nMarkdown'), truncated=False)
        assert hits[2]['payload'] == dict(url='https://page.test/article')
        assert all(hit['key'] == 'Bearer fixture-key' for hit in hits)
    finally:
        controller.abort()
        if pending is not None and not pending.done(): await asyncio.gather(pending, return_exceptions=True)
        server.shutdown(); server.server_close(); thread.join()
