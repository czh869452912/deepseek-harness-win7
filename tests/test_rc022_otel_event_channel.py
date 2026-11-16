import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.session.otel_event_channel_current import EventLogReporter
from scripts.rc022_otel_event_channel_probe import observe, cases


@pytest.mark.asyncio
async def test_actual_ordinary_event_batching_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'otel-event-channel-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==39
    for entry,row in zip(cases(),rows):
        assert row['error'] is None
        if entry['processor']['maxQueueSize']==0:assert row['captures']==[]
        if entry.get('mode')=='watchdog':assert len(row['captures'])==3 and not row['warnings']
        if entry.get('mode')=='late':assert not row['captures']
        if entry.get('mode')=='failure':assert row['warnings'][0]['message']=='Product telemetry export failed'


@pytest.mark.asyncio
async def test_each_shutdown_signal_remains_subscribed_until_shared_work_finishes():
    entered=asyncio.Event();release=asyncio.Event();closed=[]
    async def export(_):entered.set();await release.wait()
    async def flush():pass
    async def shutdown():closed.append(True)
    options=copy.deepcopy(cases()[7]);options.update(onFailure=lambda *_:None)
    channel=EventLogReporter(options,SimpleNamespace(export=export,forceFlush=flush,shutdown=shutdown))
    channel.emit(options['records'][0]);await entered.wait()
    first=AbortController();second=AbortController()
    left=channel.shutdown(first.signal);right=channel.shutdown(second.signal)
    waiter=asyncio.ensure_future(left);await asyncio.sleep(0);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    reason=RuntimeError('synthetic deadline');second.abort(reason)
    assert channel.cancellation.signal.reason is reason
    assert first.signal._listeners and not right.task.done()
    channel.emit(options['records'][0]);assert not channel.queue
    release.set();await left;await right
    assert closed==[True] and not first.signal._listeners and not second.signal._listeners


@pytest.mark.asyncio
async def test_emission_captures_record_attributes_and_observation_time():
    captured=[]
    async def export(payload):captured.append(json.loads(payload))
    async def shutdown():pass
    options=copy.deepcopy(cases()[8]);options['onFailure']=lambda *_:None
    channel=EventLogReporter(options,SimpleNamespace(export=export,shutdown=shutdown),clock=lambda:1700000000999)
    record=options['records'][0];record['attributes']['nested']={'chosen':'before'}
    channel.emit(record);record['attributes']['nested']['chosen']='after'
    await channel.shutdown()
    log=captured[0]['resourceLogs'][0]['scopeLogs'][0]['logRecords'][0]
    assert log['observedTimeUnixNano']=='1700000000999000000'
    assert next(item for item in log['attributes'] if item['key']=='nested')['value']=={
        'kvlistValue':{'values':[{'key':'chosen','value':{'stringValue':'before'}}]}}
