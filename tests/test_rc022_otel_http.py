import asyncio
import errno
import json

import pytest

from dsh.session.otel_http_current import SessionHttpExporter, log_transport_options
from scripts.rc022_otel_http_probe import observe, cases


@pytest.mark.asyncio
async def test_actual_collectors_tls_retry_and_configuration_corpus(tmp_path):
    rows = await observe()
    (tmp_path/'otel-http-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == len(cases()) == 97
    paired = list(zip(cases(), rows))
    assert len(rows[6]['hits']) == 6
    assert rows[10]['warnings'][0]['error'] == 'OTLP export response body exceeded size limit of 4194304 bytes'
    assert len(rows[12]['hits']) == 2
    for entry, row in paired:
        if entry.get('agent') in ('ca', 'identity', 'insecure', 'factory'):
            assert row['hits'] and not row['warnings']
        if entry.get('agent') in ('factory-error', 'headers-error'):
            assert row['hits'] == []
            assert row['warnings'][0]['error'] == 'synthetic callback failure'
    factory = next(row for entry, row in paired if entry.get('agent') == 'factory' and entry.get('tls'))
    assert factory['agentCalls'] == ['https:'] and len(factory['hits']) == 2


@pytest.mark.asyncio
async def test_shutdown_drains_admitted_request_and_independent_waiters():
    entered = asyncio.Event(); release = asyncio.Event(); calls = []
    exporter = SessionHttpExporter({'url':'http://fixture.invalid','concurrencyLimit':1}, environment={})
    async def run(payload):
        calls.append(payload); entered.set(); await release.wait()
    exporter._run = run
    first = exporter.export(b'first'); await entered.wait()
    with pytest.raises(RuntimeError, match='Concurrent export limit reached'):
        await exporter.export(b'second')
    closing = exporter.shutdown()
    assert closing is exporter.shutdown()
    waiter = asyncio.ensure_future(closing); await asyncio.sleep(0); waiter.cancel()
    with pytest.raises(asyncio.CancelledError): await waiter
    assert not closing.task.done() and not first.task.cancelled()
    with pytest.raises(RuntimeError, match='shut down'): await exporter.export(b'third')
    release.set(); await closing; await first
    assert calls == [b'first'] and not exporter.pending


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['headers','httpAgentOptions'])
async def test_callback_os_error_is_not_a_retryable_wire_failure(field):
    calls=[]
    def failed(*args):
        calls.append(args)
        raise OSError(errno.ECONNRESET, 'synthetic callback failure')
    exporter=SessionHttpExporter({'url':'http://fixture.invalid',field:failed}, environment={})
    with pytest.raises(OSError, match='synthetic callback failure'): await exporter.export(b'{}')
    await exporter.shutdown()
    assert len(calls)==1


def test_native_unbounded_integer_rejected_as_nonfinite_js_number():
    with pytest.raises(ValueError, match='timeoutMillis is invalid'):
        log_transport_options({'timeoutMillis':10**1000}, environment={})
