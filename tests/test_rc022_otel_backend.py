import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.cleanup import CleanupPromise
from dsh.cordis.awaiting import start_coroutine
from dsh.session.telemetry_otel_current import CurrentOpenTelemetrySessionBackend
from scripts.rc022_otel_backend_probe import observe,cases


@pytest.mark.asyncio
async def test_backend_admission_forwarding_source_envelopes_and_consent_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'otel-backend-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==42
    assert len(rows[0]['records'])==2
    assert all(record['event']['data']=={'redacted':True} for record in rows[1]['records'])
    assert not rows[2]['records'] and len(rows[2]['warnings'])==2
    assert not rows[3]['records'] and len(rows[3]['warnings'])==2
    assert not rows[4]['records'] and not rows[5]['options']


@pytest.mark.asyncio
async def test_outer_deadline_stops_queued_records_without_cancelling_owned_shutdown(tmp_path,monkeypatch):
    monkeypatch.setenv('DSH_HOME',str(tmp_path))
    ctx=Context();release=asyncio.Event();stopped=[]
    async def drain():await release.wait()
    operation=CleanupPromise(start_coroutine(drain()))
    provider=SimpleNamespace(shutdown=lambda:operation,stopPending=lambda:stopped.append(True))
    ctx.set_service('otel',SimpleNamespace(createSessionLogReporter=lambda _:provider))
    backend=CurrentOpenTelemetrySessionBackend(ctx,dict(exporter=dict(url='http://fixture.invalid'),shutdownTimeoutMillis=5))
    try:
        with pytest.raises(RuntimeError,match='provider shutdown exceeded 5ms'):await backend.shutdown()
        assert stopped==[True] and not operation.task.done()
        release.set();await operation;await backend.shutdown()
    finally:
        release.set();await operation;await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_redaction_cannot_replace_missing_source_with_unbounded_direct_record(tmp_path,monkeypatch):
    monkeypatch.setenv('DSH_HOME',str(tmp_path))
    ctx=Context();records=[];warnings=[]
    async def shutdown():pass
    ctx.logger.warn=lambda message,*_:warnings.append(message)
    ctx.set_service('otel',SimpleNamespace(createSessionLogReporter=lambda _:SimpleNamespace(
        reportSessionLog=records.append,shutdown=shutdown,stopPending=lambda:None)))
    backend=CurrentOpenTelemetrySessionBackend(ctx,dict(exporter=dict(url='http://fixture.invalid')))
    try:
        backend._export_record(dict(body={'private':'withheld'},attributes={},severity='info'))
        backend.emit(dict(sourceEvent={'sessionId':'forged'},body='direct'))
        assert not records and warnings==['Session log record withheld: redaction removed sourceEvent']
    finally:await ctx.fiber.dispose()
