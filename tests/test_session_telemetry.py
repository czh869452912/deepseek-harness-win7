import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import pytest
from dsh.cordis.context import Context
from dsh.session.telemetry import OpenTelemetrySessionBackend


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['DISABLED', 'FEEDBACK_ONLY', 'FULL'])
async def test_otel_wire_export_respects_consent(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ctx = Context()
    ctx.set_service('sessions', SimpleNamespace(list=lambda: []))
    backend = OpenTelemetrySessionBackend(ctx, dict(mode=mode, exporter=dict(url='http://127.0.0.1:%s/v1/logs' % server.server_port), processor=dict(scheduledDelayMillis=60000)))
    class Session: pass
    session = Session()
    session.id, session.firstLiveSeq = 'telemetry-test', 0
    session.header = SimpleNamespace(cwd=None, parentSession=None, seedLength=None)
    event = dict(seq=0, time=1000, type='user/message', data=dict(text='local-test-content'))
    session.events = [event]
    async def flush():
        if backend.provider is not None:
            await asyncio.get_running_loop().run_in_executor(None, backend.provider.force_flush)
    try:
        backend.event(session, event)
        await flush()
        assert bool(received) == (mode == 'FULL')
        backend.event(session, dict(seq=1, time=1001, type='feedback/record', data={}))
        await flush()
        assert bool(received) == (mode == 'FULL')
        feedback = dict(seq=1, time=1001, type='feedback/record', data=dict(consent=True))
        session.events.append(feedback)
        backend.event(session, feedback)
        await flush()
        assert bool(received) == (mode != 'DISABLED')
        if received:
            from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
            packets = [ExportLogsServiceRequest.FromString(body) for body in received]
            logs = [record for packet in packets for resource in packet.resource_logs for scope in resource.scope_logs for record in scope.log_records]
            assert len(logs) == 2
    finally:
        await backend.shutdown()
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        thread.join(2)
