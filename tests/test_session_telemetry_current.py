"""Real JSON collector plus feedback ownership and cold storage."""
import asyncio
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.core.session.current_session import CurrentSessionPlugin, CurrentSession
from dsh.session.telemetry_otel_current import CurrentOpenTelemetrySessionBackend
from dsh.session.otel_service_current import CurrentOTel
from scripts.oracles.telemetry_current_python import execute
from tests.test_feedback_current import cold_fixture


CASES = json.loads((Path(__file__).parents[1] / 'scripts/oracles/telemetry_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case'])
def test_actual_current_capture_contract(case):
    assert execute(case) == case['expected']


@pytest.fixture
def collector():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.extend(request['resourceLogs'])
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    class Collector:
        config = dict(exporter=dict(url='http://127.0.0.1:%s/v1/logs' % server.server_port), processor=dict(scheduledDelayMillis=60000))
        async def flush(self, backend):
            if backend.provider is not None:
                await backend.provider.forceFlush()
        def types(self):
            return [attribute['value']['stringValue'] for resource in received for scope in resource['scopeLogs']
                    for record in scope['logRecords'] for attribute in record['attributes'] if attribute['key'] == 'event.type']
    item = Collector()
    item.resources = received
    try:
        yield item
    finally:
        server.shutdown();server.server_close();thread.join(2)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', [None, 'FEEDBACK_ONLY', 'DISABLED'])
async def test_actual_otel_authorizes_only_canonical_own_feedback(tmp_path, monkeypatch, collector, mode):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    ctx = Context()
    await ctx.plugin(CurrentSessionPlugin)
    await ctx.plugin(CurrentOTel)
    config = dict(collector.config, mode=mode)
    config['processor'] = dict(config['processor'], maxExportBatchSize=1.0)
    await ctx.plugin(CurrentOpenTelemetrySessionBackend, config)
    backend = ctx.get('sessionTelemetry')
    session = ctx.get('sessions').create('live')
    try:
        session.append('turn/start', dict(turn=1))
        backend.emit(dict(channel='ops', time=1, severity='info', attributes={}, body='direct'))
        session.append('feedback/message-delete', dict(sessionId='other', messageId='m'))
        ctx.emit('session/event', session, dict(type='feedback/record', seq=1, time=1, data={}))
        await collector.flush(backend)
        assert not collector.types()
        session.append('feedback/record', dict(text='explicit'))
        await collector.flush(backend)
        expected = [] if mode == 'DISABLED' else ['turn/start', 'feedback/message-delete', 'feedback/record']
        assert collector.types() == expected
        # A forged clone cannot authorize a suffix even when its seq is real.
        session.append('turn/end', dict(turn=1, reason=dict(kind='completed')))
        ctx.emit('session/event', session, copy.deepcopy(session.events[-2]))
        await collector.flush(backend)
        assert collector.types() == expected
        session.append('feedback/message-delete', dict(sessionId='live', messageId='m'))
        await collector.flush(backend)
        if mode != 'DISABLED':
            expected += ['turn/end', 'feedback/message-delete']
        assert collector.types() == expected
        for resource in collector.resources:
            assert next(a['value']['stringValue'] for a in resource['resource']['attributes'] if a['key'] == 'service.version') == '0.2.2-rc.3'
            assert all(scope['scope']['version'] == '0.2.2-rc.3' and not scope['scope']['name'].endswith('/ops') for scope in resource['scopeLogs'])
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_full_mode_rejected_before_service_or_sdk_registration():
    ctx = Context()
    with pytest.raises(ValueError, match='unsupported mode'):
        CurrentOpenTelemetrySessionBackend(ctx, dict(mode='FULL'))
    assert ctx.get('sessionTelemetry') is None
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_seeded_feedback_is_not_consent_until_child_submits_new_feedback(tmp_path, monkeypatch, collector):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    ctx = Context()
    await ctx.plugin(CurrentSessionPlugin)
    await ctx.plugin(CurrentOTel)
    parent = ctx.get('sessions').create('parent')
    parent.append('feedback/record', dict(text='parent-consent'))
    child = ctx.get('sessions').fork(parent, child_session_id='child')
    await ctx.plugin(CurrentOpenTelemetrySessionBackend, collector.config)
    backend = ctx.get('sessionTelemetry')
    try:
        ctx.emit('session/event', child, child.events[0])
        await collector.flush(backend)
        assert not collector.types()
        child.append('feedback/record', dict(text='child-consent'))
        await collector.flush(backend)
        assert collector.types() == ['feedback/record', 'session/end-seed', 'feedback/record']
        records = [record for resource in collector.resources for scope in resource['scopeLogs'] for record in scope['logRecords']]
        assert all(next(a['value']['stringValue'] for a in record['attributes'] if a['key'] == 'session.id') == 'child' for record in records)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_cold_feedback_submission_exports_stored_history_and_exact_prefix(tmp_path, monkeypatch, collector):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    ctx, _ = await cold_fixture(tmp_path / 'sessions')
    await ctx.plugin(CurrentOTel)
    await ctx.plugin(CurrentOpenTelemetrySessionBackend, collector.config)
    backend = ctx.get('sessionTelemetry')
    try:
        assert ctx.get('sessions').get('cold') is None
        result = await ctx.get('messageFeedback').put(dict(sessionId='cold', messageId='message', rating='positive', ifVersion=None))
        assert result['ok']
        await collector.flush(backend)
        assert collector.types() == ['assistant/message', 'feedback/message-put']
        assert ctx.get('sessions').get('cold') is None
        # No-op submits and reads do not commit another authorization event.
        result = await ctx.get('messageFeedback').put(dict(sessionId='cold', messageId='message', rating='positive', ifVersion=result['value']['version']))
        assert result['ok']
        await collector.flush(backend)
        assert collector.types() == ['assistant/message', 'feedback/message-put']
    finally:
        await ctx.fiber.dispose()
