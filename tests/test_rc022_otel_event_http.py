import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.session.otel_event_http_current import EventHttpExporter
from scripts.rc022_otel_event_http_probe import observe, cases


@pytest.mark.asyncio
async def test_actual_event_transport_status_cancellation_tls_and_decoding(tmp_path):
    rows=await observe()
    (tmp_path/'otel-event-http-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==43
    for entry,row in zip(cases(),rows):
        if entry.get('agent')=='factory':assert row['agentDestroyed']==1
        if entry.get('abort')=='before':assert not row['hits']
        if entry.get('abort')=='delay':
            assert row['warnings'][0]['error']=='This operation was aborted.'
            assert len(row['hits'])==1
        if entry.get('responseEncoding'):
            if entry['mode']=='oversized':assert row['warnings'][0]['error']=='Promise was canceled'
            else:assert row['hits'] and not row['warnings']
    assert rows[12]['warnings'][0]['error']=='socket hang up'
    assert len(rows[12]['hits'])==1


@pytest.mark.asyncio
async def test_preaborted_custom_reason_keeps_identity_and_does_not_create_agent():
    controller=AbortController();reason=RuntimeError('synthetic');controller.abort(reason)
    calls=[]
    exporter=EventHttpExporter({'url':'http://fixture.invalid','httpAgentOptions':lambda *_:calls.append(True)},controller.signal,environment={})
    with pytest.raises(RuntimeError) as failure:await exporter.export(b'{}')
    assert failure.value is reason and not calls
    await exporter.shutdown();assert controller.signal._listeners==[]


@pytest.mark.asyncio
async def test_shutdown_destroys_factory_agent_once_after_request_settles():
    entered=asyncio.Event();release=asyncio.Event();destroyed=[]
    agent=SimpleNamespace(destroy=lambda:destroyed.append(True))
    exporter=EventHttpExporter({'url':'http://fixture.invalid','httpAgentOptions':lambda _:agent},environment={})
    async def request(*_):
        entered.set();await release.wait();return {'status':200}
    exporter._request=request
    pending=exporter.export(b'{}');await entered.wait()
    closing=exporter.shutdown();assert closing is exporter.shutdown() and not destroyed
    waiter=asyncio.ensure_future(closing);await asyncio.sleep(0);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    release.set();await closing;await pending
    assert destroyed==[True]
