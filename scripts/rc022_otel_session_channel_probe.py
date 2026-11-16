"""Actual byte/count Session channel operations over an explicit exporter port."""
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
    base=wire_cases()[0];rows=[]
    for count in [0,1,2,3,8]:
        for batch,queue in [(1,2),(2,2),(2,4),(4,4),(512,2048)]:
            entry=copy.deepcopy(base);entry.update(records=entry['records']*count,
                processor=dict(maxExportBatchSize=batch,maxQueueSize=queue))
            rows.append(entry)
    for limit in [1,500,841,842,843,1683,1684,4000000]:
        entry=copy.deepcopy(base);entry.update(records=entry['records']*3,maxRequestBytes=limit);rows.append(entry)
    for mode in ['watchdog','stop','timer','late']:
        entry=copy.deepcopy(base);entry.update(mode=mode,records=entry['records']*4,
            processor=dict(maxExportBatchSize=1 if mode!='timer' else 512,maxQueueSize=2,
                scheduledDelayMillis=10 if mode=='timer' else 2147483647,exportTimeoutMillis=100))
        if mode=='timer': entry['processor']['maxQueueSize']=2048
        rows.append(entry)
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.session.otel_session_channel_current import SessionLogReporter
    rows=[]
    for entry in cases():
        captures=[];warnings=[];error=None;reporter=None
        entered=asyncio.Event();release=asyncio.Event();warned=asyncio.Event();mode=entry.get('mode')
        def warning(message,failure=None):
            warnings.append(dict(message=message,error=None if failure is None else str(failure)))
            if 'exceeded exportTimeoutMillis' in message:warned.set()
        async def export(payload):
            captures.append(dict(document=json.loads(payload),bytes=len(payload)));entered.set()
            if mode in ('watchdog','stop') and len(captures)==1:await release.wait()
        async def shutdown():pass
        options=dict(entry,onFailure=warning)
        options['processor']=dict(scheduledDelayMillis=2147483647,**entry.get('processor',{})) if 'scheduledDelayMillis' not in entry.get('processor',{}) else entry['processor']
        try:
            reporter=SessionLogReporter(options,SimpleNamespace(export=export,shutdown=shutdown))
            records=entry['records']
            if mode=='late':
                await reporter.shutdown()
                for record in records:reporter.reportSessionLog(record)
            elif mode in ('watchdog','stop'):
                reporter.reportSessionLog(records[0]);await asyncio.wait_for(entered.wait(),5)
                if mode=='watchdog':await asyncio.wait_for(warned.wait(),5)
                for record in records[1:]:reporter.reportSessionLog(record)
                if mode=='stop':reporter.stopPending()
                release.set();await reporter.shutdown()
            else:
                for record in records:reporter.reportSessionLog(record)
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
    probe.main('rc022_otel_session_channel.mts',
        'Source actual Session-log HTTP batches versus actual Native channel over controlled exporter: count/byte admission, queue overflow, watchdog settlement, stopPending, timer and shutdown admission.',
        [Path(__file__).resolve(),ROOT/'dsh/session/otel_session_channel_current.py'],prepare=prepare)
