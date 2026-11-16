import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from dsh.session.otel_session_channel_current import SessionLogReporter
from scripts.rc022_otel_session_channel_probe import observe, cases


@pytest.mark.asyncio
async def test_actual_session_channel_batching_and_lifetime_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'otel-session-channel-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==37
    assert any(row['warnings'] and 'queue is full' in row['warnings'][0]['message'] for row in rows)
    assert rows[-4]['warnings'][0]['message'].startswith('Session log request exceeded')
    assert len(rows[-3]['captures'])==1
    assert rows[-1]['captures']==[]


@pytest.mark.asyncio
async def test_shared_flush_shutdown_waiters_do_not_cancel_owned_export():
    entered=asyncio.Event();release=asyncio.Event();captured=[];closed=[]
    async def export(payload):
        captured.append(json.loads(payload));entered.set();await release.wait()
    async def shutdown():closed.append(True)
    options=copy.deepcopy(cases()[0]);options.update(onFailure=lambda *_:None,
        processor=dict(maxQueueSize=4,maxExportBatchSize=1,scheduledDelayMillis=10000))
    channel=SessionLogReporter(options,SimpleNamespace(export=export,shutdown=shutdown))
    record=cases()[5]['records'][0]
    channel.reportSessionLog(record)
    await entered.wait()
    first=channel.forceFlush();assert first is channel.forceFlush()
    waiter=asyncio.ensure_future(first);await asyncio.sleep(0);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    closing=channel.shutdown();assert closing is channel.shutdown()
    assert not first.task.cancelled() and not closing.task.done()
    release.set();await closing
    assert len(captured)==1 and closed==[True]
    assert channel.active is None and channel.timer is None


@pytest.mark.asyncio
async def test_export_failure_settles_then_next_batch_and_independent_channel_continue():
    warnings=[];sent=[];shutdowns=[]
    def export(payload):
        sent.append(json.loads(payload))
        if len(sent)==1:raise RuntimeError('injected exporter failure')
    def shutdown():shutdowns.append(True)
    options=copy.deepcopy(cases()[0]);options.update(onFailure=lambda message,error=None:warnings.append((message,str(error))),
        processor=dict(maxQueueSize=4,maxExportBatchSize=1,scheduledDelayMillis=10000))
    first=SessionLogReporter(options,SimpleNamespace(export=export,shutdown=shutdown))
    second_sent=[]
    second=SessionLogReporter(options,SimpleNamespace(export=lambda payload:second_sent.append(payload),shutdown=lambda:None))
    record=cases()[5]['records'][0]
    first.reportSessionLog(record);first.reportSessionLog(record)
    second.reportSessionLog(record)
    await asyncio.gather(first.shutdown(),second.shutdown())
    assert len(sent)==2 and len(second_sent)==1 and shutdowns==[True]
    assert warnings==[('Session log export failed','injected exporter failure')]


@pytest.mark.asyncio
async def test_constructor_options_and_emitted_content_have_separate_ownership():
    captured=[];warnings=[]
    options=copy.deepcopy(cases()[0]);options.update(onFailure=lambda *args:warnings.append(args),
        processor=dict(maxQueueSize=2048,maxExportBatchSize=512,scheduledDelayMillis=10000))
    channel=SessionLogReporter(options,SimpleNamespace(export=lambda payload:captured.append(json.loads(payload)),shutdown=lambda:None))
    record=copy.deepcopy(cases()[5]['records'][0]);channel.reportSessionLog(record)
    record['event']['data']['text']='changed-after-emission'
    options['scope']['name']='changed-after-construction'
    options['resourceAttributes']['new']='changed-after-construction'
    await channel.shutdown()
    resource=captured[0]['resourceLogs'][0];scope=resource['scopeLogs'][0]
    assert scope['scope']['name']=='fixture'
    assert 'new' not in [item['key'] for item in resource['resource']['attributes']]
    content=next(item['value']['stringValue'] for item in scope['logRecords'][0]['attributes'] if item['key']=='content')
    assert json.loads(content)['data']['text']=='synthetic'
    assert warnings==[]
