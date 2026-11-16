import asyncio
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.cordis.context import Context
from dsh.session.otel_service_current import CurrentOTel
from scripts.rc022_product_telemetry_probe import observe,cases


@pytest.mark.asyncio
async def test_product_policy_configuration_and_disposal_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'product-telemetry-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==119
    assert rows[0]['options'][0]['resourceAttributes']=={'service.name':'fixture','service.version':'1'}
    assert rows[2]['shutdown']==[{'aborted':True,'reason':'Product telemetry shutdown deadline exceeded'}]
    assert rows[2]['warnings']==['Product telemetry shutdown deadline exceeded; pending events may be lost']
    assert all(not row['after'] for row in rows)
    explicit_null=next(row for entry,row in zip(cases(),rows) if entry['config']=={'compression':None})
    assert explicit_null['options'][0]['exporter']['compression']=='none'


@pytest.fixture
def collectors():
    owned=[]
    def create(hold=False):
        hits=[];entered=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['content-length']))
                if self.headers.get('content-encoding')=='gzip':raw=gzip.decompress(raw)
                hits.append(dict(document=json.loads(raw),channel=self.headers.get('x-channel'),
                    compression=self.headers.get('content-encoding'),authorization=self.headers.get('authorization')))
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();entered.set()
                if hold:release.wait(10)
                try:self.wfile.write(b'{}')
                except OSError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01));thread.start()
        value=SimpleNamespace(server=server,thread=thread,hits=hits,entered=entered,release=release,
            url='http://127.0.0.1:'+str(server.server_port)+'/logs')
        owned.append(value);return value
    try:yield create
    finally:
        for value in owned:
            value.release.set();value.server.shutdown();value.server.server_close();value.thread.join()


@pytest.mark.asyncio
@pytest.mark.parametrize('compression',['gzip','none',None,'omitted'])
async def test_actual_product_event_channel_http_identity_headers_and_compression(collectors,monkeypatch,compression):
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_LOGS_COMPRESSION','gzip')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS','authorization=not-ours')
    collector=collectors();ctx=Context();await ctx.plugin(CurrentOTel)
    config=dict(endpoint=collector.url,serviceName='fixture-product',serviceVersion='1',channel='fixture-channel',scheduledDelayMillis=100000)
    if compression!='omitted':config['compression']=compression
    fiber=ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-host-product-telemetry-otel'),config);await fiber
    try:
        assert collector.hits==[]
        ctx.get('productTelemetry').emit(dict(eventName='fixture',body='synthetic',timestamp=1700000000000,attributes={'platform':'win32'}))
        await fiber.dispose()
        assert len(collector.hits)==1
        hit=collector.hits[0]
        assert hit['channel']=='fixture-channel' and hit['authorization'] is None
        assert hit['compression']==('gzip' if compression in ('gzip','omitted') else None)
        resource=hit['document']['resourceLogs'][0]
        assert resource['resource']['attributes']==[
            {'key':'service.name','value':{'stringValue':'fixture-product'}},
            {'key':'service.version','value':{'stringValue':'1'}}]
        scope=resource['scopeLogs'][0]
        assert scope['scope']=={'name':'@deepseek-ai/dsh-host-product-telemetry-otel'}
        assert scope['logRecords'][0]['body']=={'stringValue':'synthetic'}
        assert ctx.get('productTelemetry',False) is None and ctx.get('otel') is not None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_fiber_deadline_cancels_stalled_actual_http_body(collectors):
    collector=collectors(hold=True);ctx=Context();await ctx.plugin(CurrentOTel)
    fiber=ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-host-product-telemetry-otel'),dict(
        endpoint=collector.url,serviceName='fixture-product',serviceVersion='1',maxExportBatchSize=1,shutdownTimeoutMillis=5));await fiber
    try:
        ctx.get('productTelemetry').emit(dict(eventName='fixture',body='synthetic',timestamp=1700000000000))
        assert await asyncio.get_running_loop().run_in_executor(None,collector.entered.wait,5)
        await asyncio.wait_for(fiber.dispose(),2)
        warnings=[message.args[0] for message in ctx.logger.buffer if message.type=='warn']
        assert 'Product telemetry shutdown deadline exceeded; pending events may be lost' in warnings
        assert 'Product telemetry export failed' in warnings
        assert len(collector.hits)==1 and ctx.get('productTelemetry',False) is None
    finally:
        collector.release.set();await ctx.fiber.dispose()
