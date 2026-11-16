"""Actual ordinary-event SDK batching versus Native count-channel operations."""
import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_otel_wire_probe import cases as wire_cases


def cases():
    base=wire_cases()[1];rows=[]
    for count in [0,1,2,3,8]:
        for batch,queue in [(1,2),(2,2),(2,4),(4,4),(512,2048),(4,2),(1,0)]:
            entry=copy.deepcopy(base);entry.update(records=entry['records']*count,
                processor=dict(maxExportBatchSize=batch,maxQueueSize=queue));rows.append(entry)
    for mode in ['watchdog','timer','late','failure']:
        entry=copy.deepcopy(base);entry.update(mode=mode,records=entry['records']*4,
            processor=dict(maxExportBatchSize=512 if mode=='timer' else 1,maxQueueSize=2048 if mode=='timer' else 2,
                scheduledDelayMillis=10 if mode=='timer' else 2147483647,exportTimeoutMillis=30 if mode=='watchdog' else 30000))
        rows.append(entry)
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.session.otel_event_channel_current import EventLogReporter
    from dsh.core.cleanup import CleanupPromise
    from dsh.cordis.awaiting import start_coroutine
    rows=[]
    for entry in cases():
        captures=[];warnings=[];pending=set();entered=asyncio.Event();second=asyncio.Event();release=asyncio.Event()
        mode=entry.get('mode');error=None;reporter=None
        async def send(payload):
            captures.append(dict(document=json.loads(payload),bytes=len(payload)));entered.set()
            if len(captures)==2:second.set()
            if mode=='watchdog' and len(captures)==1:await release.wait()
            if mode=='failure':raise RuntimeError('Request failed with status code 400 (Bad Request): POST <collector>')
        def export(payload):
            promise=CleanupPromise(start_coroutine(send(payload)));pending.add(promise)
            promise.add_done_callback(lambda _:pending.discard(promise));return promise
        async def flush():
            if pending:await asyncio.gather(*list(pending),return_exceptions=True)
        async def shutdown():await flush()
        options=dict(entry,onFailure=lambda message,failure=None:warnings.append(dict(message=message,error=None if failure is None else str(failure))))
        options['processor']=dict(scheduledDelayMillis=2147483647,**entry['processor']) if 'scheduledDelayMillis' not in entry['processor'] else entry['processor']
        try:
            reporter=EventLogReporter(options,SimpleNamespace(export=export,forceFlush=flush,shutdown=shutdown),clock=lambda:1700000000999)
            if mode=='late':
                await reporter.shutdown()
                for record in entry['records']:reporter.emit(record)
            elif mode=='watchdog':
                reporter.emit(entry['records'][0]);await asyncio.wait_for(entered.wait(),5)
                for record in entry['records'][1:]:reporter.emit(record)
                await asyncio.wait_for(second.wait(),5);release.set();await reporter.shutdown()
            else:
                for record in entry['records']:reporter.emit(record)
                if mode=='timer':await asyncio.wait_for(entered.wait(),5)
                await reporter.shutdown()
        except Exception as failure:error=str(failure)
        finally:
            release.set()
            if reporter is not None:await reporter.shutdown()
        rows.append(dict(captures=captures,warnings=warnings,error=error))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_otel_event_channel.mts','Source actual EventLogReporter HTTP batches versus Native ordinary-event count channel over a controlled exporter port.',
        [Path(__file__).resolve(),ROOT/'dsh/session/otel_event_channel_current.py'],prepare=prepare)
