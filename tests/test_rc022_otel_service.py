import hashlib
import json
from pathlib import Path

import pytest

from dsh.boot.app_boot import boot
from dsh.session.otel_service_current import CurrentOTel
from scripts.rc022_otel_service_probe import observe


@pytest.mark.asyncio
async def test_actual_service_factories_and_independent_end_to_end_channels(tmp_path):
    rows=await observe()
    (tmp_path/'otel-service-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==5 and all(row['mounted'] and not row['after'] for row in rows)
    assert rows[0]['captures']==[]
    for row in rows[1:3]:
        assert not row['warnings'] and row['error'] is None
        assert [capture['path'] for capture in row['captures']]==['/event-a','/event-b','/session-a','/session-b']
        assert [len(capture['document']['resourceLogs'][0]['scopeLogs'][0]['logRecords']) for capture in row['captures']]==[1,2,1,2]
    assert 'maxRequestBytes' in rows[3]['error'] and 'timeoutMillis' in rows[4]['error']


@pytest.mark.asyncio
async def test_canonical_boot_mounts_service_and_unloads_without_creating_network(tmp_path,monkeypatch):
    def forbidden(*_,**__):raise AssertionError('Mounting otel must not create a collector request')
    monkeypatch.setattr('dsh.session.otel_http_current.open_stream',forbidden)
    monkeypatch.setattr('dsh.session.otel_event_http_current.open_stream',forbidden)
    config=tmp_path/'cordis.yml'
    config.write_text("- id: otel\n  name: '@deepseek-ai/dsh-otel'\n",encoding='utf-8')
    ctx=await boot('dsh',str(config))
    try:
        service=ctx.get('otel')
        assert service is not None and isinstance(getattr(service,'_target',service),CurrentOTel)
        assert callable(service.createSessionLogReporter) and callable(service.createEventReporter)
    finally:await ctx.fiber.dispose()
    assert ctx.get('otel',False) is None


def test_service_manifest_is_exact_pinned_source_metadata():
    root=Path(__file__).resolve().parents[1]
    manifest=root/'packages/telemetry/otel/package.json'
    assert json.loads(manifest.read_text(encoding='utf-8'))['version']=='0.2.2-rc.3'
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()=='f6db74a6dae13472f1bd724f54df02b789212088b9e705f944e31fd62a2d8923'
