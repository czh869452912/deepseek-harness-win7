"""Backend-owned admission, source envelopes and feedback authorization over an otel port."""
import asyncio
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
UUID='12345678-1234-4234-8234-123456789abc'


def cases():
    rows=[dict(config=dict(mode='DISABLED' if mode=='disabled' else 'FEEDBACK_ONLY'),action=mode)
        for mode in ['capture','redact','remove-source','noncanonical','seeded','disabled']]
    values=[None,False,0,-1,1,1.5,2147483648,'1',{},[]]
    for field in ['mode','shutdownTimeoutMillis']:
        rows += [dict(config={field:value},action='none') for value in values]
    rows += [dict(config=dict(exporter=dict(url=value)),action='none') for value in [None,'','relative','file:///logs','ftp://fixture/logs','http://fixture.test/logs']]
    rows += [dict(config=dict(processor=dict(maxExportBatchSize=value)),action='none') for value in values]
    return rows


def prepare(output):
    home=output/'files/source-home';home.mkdir(parents=True)
    (home/'.anonymous-user-id').write_text(UUID+'\n',encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path,home/'.anonymous-user-id']


async def observe():
    from dsh.cordis.context import Context
    from dsh.session.telemetry_otel_current import CurrentOpenTelemetrySessionBackend
    rows=[]
    with tempfile.TemporaryDirectory(prefix='dsh-otel-backend-') as directory:
        home=Path(directory);(home/'.anonymous-user-id').write_text(UUID+'\n',encoding='utf-8')
        previous=os.environ.get('DSH_HOME');os.environ['DSH_HOME']=str(home)
        try:
            for entry in cases():
                ctx=Context();options=[];records=[];warnings=[];error=None
                ctx.logger.warn=lambda message,*_:warnings.append(str(message))
                async def shutdown():pass
                def create(selected):
                    options.append(copy.deepcopy({key:value for key,value in selected.items() if key!='onFailure'}))
                    return SimpleNamespace(reportSessionLog=lambda value:records.append(copy.deepcopy(value)),shutdown=shutdown,stopPending=lambda:None)
                ctx.set_service('otel',SimpleNamespace(createSessionLogReporter=create))
                ctx.set_service('sessions',SimpleNamespace(list=lambda:[]))
                def redact(record,next_fn):
                    if entry['action']=='redact':record['body']={'redacted':True}
                    if entry['action']=='remove-source':record.pop('sourceEvent',None)
                    return next_fn()
                ctx.on('session-telemetry/record',redact)
                config=dict(exporter=dict(url='http://fixture.test/logs'),**{key:value for key,value in entry['config'].items() if key!='exporter'})
                if 'exporter' in entry['config']:config['exporter']=entry['config']['exporter']
                try:
                    backend=CurrentOpenTelemetrySessionBackend(ctx,config)
                    events=[dict(seq=0,time=1700000000000,type='fixture/synthetic',data={'text':'private'}),
                        dict(seq=1,time=1700000000001,type='feedback/record',data={'text':'consent'})]
                    class Session:pass
                    session=Session();session.id='fixture';session.events=events
                    session.inheritedEventCount=2 if entry['action']=='seeded' else 0;session.firstLiveSeq=0
                    session.header=SimpleNamespace(version=4,cwd='/workspace',parentSession=None,isSeeded=False)
                    session.snapshotEvents=lambda offset=0:events[int(offset):];session.eventAt=lambda seq:events[seq]
                    backend.emit(dict(channel='ledger',time=1,severity='info',attributes={},body={'direct':'withheld'}))
                    if entry['action']!='none':
                        event=copy.deepcopy(events[-1]) if entry['action']=='noncanonical' else events[-1]
                        ctx.emit('session/event',session,event);ctx.emit('session/event',session,event)
                    await backend.shutdown()
                except Exception as failure:error=str(failure)
                finally:await ctx.fiber.dispose()
                rows.append(dict(options=options,records=records,warnings=warnings,error=error))
        finally:
            if previous is None:os.environ.pop('DSH_HOME',None)
            else:os.environ['DSH_HOME']=previous
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_otel_backend.mts','Actual feedback-only backend constructors, forwarded otel options, canonical source envelopes, redaction and authorization over controlled reporter ports.',
        [Path(__file__).resolve(),ROOT/'dsh/session/telemetry_otel_current.py'],prepare=prepare)
