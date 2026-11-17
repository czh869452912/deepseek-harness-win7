"""Current task admission/normalization, v1 bytes and saved history against Source."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_schedule_update_probe import TIMINGS,NOW
from dsh.schedule.update_current import create_schedule_record

FILES=None
STAMP='2026-09-16T00:01:00.000Z'

def receipt(index=0,**patch):return dict(scheduledAt=STAMP,deliveredAt=STAMP,messageId='message-'+str(index),**patch)

def cases():
    record=json.loads(json.dumps(create_schedule_record('id','title','prompt',TIMINGS[0],NOW)))
    base=dict(record=record);rows=[]
    def add(task):rows.append(dict(op='parse',task=task))
    for patch in [{},dict(sessionId='old'),dict(sessionId=' '),dict(sessionId=''),dict(sessionId=None),dict(sessionId=123),
        dict(status='inactive'),dict(status='paused'),dict(status='ended'),dict(status=None),dict(status='invalid'),
        dict(target=dict(kind='session',sessionId='explicit'),sessionId=dict(invalid=True)),
        dict(target=dict(kind='session',sessionId='')),dict(target=dict(kind='new_once')),
        dict(target=dict(kind='new_once',create=dict(cwd='C:/work',agentPreset='minimal'))),
        dict(target=dict(kind='new_once',sessionId='reserved')),dict(target=dict(kind='new')),
        dict(target=dict(kind='new',create=dict(cwd=' '))),dict(target=dict(kind='new',create=dict(cwd=''))),
        dict(target=dict(kind='new',extra=1)),dict(target=dict(kind='new',sessionId='bad')),
        dict(target=dict(kind='new',create=None)),dict(target=dict(kind='new',create=dict(extra=1))),dict(target=dict(kind='bad')),
        dict(involvedSessionIds=[]),dict(involvedSessionIds=['x','x',' ']),dict(involvedSessionIds=['']),dict(involvedSessionIds=None),
        dict(createdAt=STAMP,updatedAt=STAMP),dict(createdAt='0000-02-29T00:00:00.000Z'),
        dict(createdAt='2026-02-29T00:00:00.000Z'),dict(updatedAt='2026-09-16T00:00:00Z'),
        dict(pendingDelivery=dict(targetSessionId='reserved')),dict(pendingDelivery=dict(targetSessionId='')),
        dict(pendingDelivery=dict(targetSessionId='s',extra=1)),dict(extra=True)]:add(dict(base,**patch))
    for identity in ['normal',' 中文 ','emoji-\U0001f600','lone-\ud800','pair-\ud83d\ude00','constructor']:
        add(dict(record=dict(record,id=identity)))
    for target in [{},dict(sessionId='old'),dict(target=dict(kind='session',sessionId='saved')),
        dict(target=dict(kind='new_once')),dict(target=dict(kind='new_once',sessionId='reserved')),dict(target=dict(kind='new'))]:
        for ack in [receipt(),receipt(targetSessionId='actual')]:add(dict(base,lastDelivery=ack,**target))
    for patch in [dict(messageId=''),dict(messageId=' spaced '),dict(targetSessionId=''),dict(extra=True),dict(deliveredAt=None)]:
        ack=receipt();ack.update(patch);add(dict(base,sessionId='old',lastDelivery=ack))
    for history,last in [
        (dict(records=[],earlierRecordsUnavailable=False),None),
        (dict(records=[receipt(prompt='sent')],earlierRecordsUnavailable=False),receipt()),
        (dict(records=[receipt(prompt='sent')],earlierRecordsUnavailable=False),None),
        (dict(records=[],earlierRecordsUnavailable=False),receipt()),
        (dict(records=[receipt(),receipt()],earlierRecordsUnavailable=False),receipt()),
        (dict(records=[receipt(prompt=None)],earlierRecordsUnavailable=False),receipt()),
        (dict(records=[],earlierRecordsUnavailable=None),None),
        (dict(records=[],earlierRecordsUnavailable=False,earlierRecordsPruned=True),None),
        (dict(records=[],earlierRecordsUnavailable=False,extra=True),None)]:
        add(dict(base,sessionId='old',deliveryHistory=history,**({} if last is None else dict(lastDelivery=last))))
    for timing in TIMINGS:
        current=json.loads(json.dumps(create_schedule_record('id','title','prompt',timing,NOW)))
        rows.append(dict(op='store',task=dict(record=current,sessionId='old',status='inactive')))
    for value in [None,[],{},dict(record=None),dict(record=dict(record,extra=1))]:add(value)
    history=[dict(receipt(index),deliveredAt='2026-09-'+('16' if index%2==0 else '15')+'T00:01:00.000Z',prompt='sent-'+str(index),targetSessionId='old') for index in range(7)]
    last={key:value for key,value in history[-1].items() if key!='prompt'}
    saved=dict(base,sessionId='old',lastDelivery=last,deliveryHistory=dict(records=history,earlierRecordsUnavailable=False))
    for limit,before in [(1,None),(3,None),(3,'message-3'),(10,'message-0'),(1,'unknown')]:
        rows.append(dict(op='page',task=saved,request=dict(id='id',limit=limit,**({} if before is None else dict(before=before))),bounds=dict(days=30,records=200)))
    for days,cap in [(30,200),(30,3),(1,200),(1,1)]:
        rows.append(dict(op='append',task=saved,receipt=dict(receipt(7),deliveredAt='2026-09-17T00:01:00.000Z',targetSessionId='new'),bounds=dict(days=days,records=cap)))
    return rows

def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir()
    path=output/'inputs.json';path.write_text(json.dumps(dict(cases=cases(),files=str(FILES))),encoding='utf-8');return [path]

def observed_error(error):
    return sorted([dict(code=issue['code'],path=issue['path']) for issue in error.issues],key=lambda issue:json.dumps(issue,sort_keys=True))

async def observe(files=None):
    from dsh.schedule.storage_current import parse_schedule_task
    from dsh.schedule.delivery_history_current import append_delivery,delivery_history_page
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.backend import KvUnitDescriptor
    files=Path(files or FILES);files.mkdir(exist_ok=True,parents=True);rows=[]
    for index,entry in enumerate(cases()):
        try:
            task=parse_schedule_task(entry['task']);op=entry['op']
            if op=='parse':value=task
            elif op=='page':value=delivery_history_page(task,entry['request'],entry['bounds'])
            elif op=='append':value=append_delivery(task,entry['receipt'],entry['bounds'])
            else:
                folder=files/('native-'+str(index));folder.mkdir();path=folder/'schedule.json'
                before=json.dumps(dict(unit=dict(name='schedule',version=1),global_=None,tables=dict(tasks=dict(id=entry['task'])))).replace('global_','global')
                path.write_text(before,encoding='utf-8');backend=JsonStorageBackend(str(folder));desc=KvUnitDescriptor('schedule',2,['tasks'],compatible_versions=[1])
                try:
                    unit=await backend.kv.open(desc);raw=(await unit.load_all())['tables']['tasks']['id'];normalized=parse_schedule_task(raw)
                    unchanged=path.read_text(encoding='utf-8')==before
                    revised=dict(normalized,updatedAt=STAMP);await unit.put_record('tasks','id',revised);await unit.close()
                    unit=await backend.kv.open(desc)
                    value=dict(normalized=normalized,unchanged=unchanged,disk=json.loads(path.read_text(encoding='utf-8')),cold=parse_schedule_task((await unit.load_all())['tables']['tasks']['id']))
                finally:await backend.close()
            rows.append(dict(op=entry['op'],success=True,value=value))
        except Exception as error:
            if not hasattr(error,'issues'):raise
            rows.append(dict(op=entry['op'],success=False,issues=observed_error(error)))
    return json.loads(json.dumps(rows))

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_storage.mts',prepare=prepare,
        scope='Task admission and normalized values; sorted issue paths/codes only. Seven v1 JSON read/no-write/current publish/cold reopen journeys; history pagination and retention.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/schedule/storage_current.py',ROOT/'dsh/schedule/delivery_history_current.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/schedule/schedule/src/storage.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/schedule/schedule/src/delivery-history.ts'])
