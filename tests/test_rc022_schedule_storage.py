import copy
import json

import pytest

from dsh.schedule.storage_current import parse_schedule_task,schedule_domain
from dsh.schedule.delivery_history_current import delivery_history_page,append_delivery
from dsh.storage.domain_impl import DomainFacility
from dsh.storage import storage_json
from scripts.rc022_schedule_storage_probe import observe,cases,STAMP,receipt


@pytest.mark.asyncio
async def test_task_and_history_observations(tmp_path):
    rows=await observe(tmp_path/'files')
    (tmp_path/'schedule-storage-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    stores=[row['value'] for row in rows if row['op']=='store']
    assert len(stores)==7 and all(row['unchanged'] and row['disk']['unit']['version']==2 for row in stores)
    assert all('sessionId' not in row['cold'] and row['cold']['status']=='ended' for row in stores)
    lone=next(row for row in rows if row.get('value',{}).get('record',{}).get('id')=='lone-\ud800')
    assert lone['value']['target']['sessionId'].startswith('session-schedule-')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',range(7))
async def test_actual_domain_compatible_read_does_not_write_or_touch_sessions(tmp_path,monkeypatch,kind):
    task=[entry['task'] for entry in cases() if entry['op']=='store'][kind]
    path=tmp_path/'schedule.json';before=json.dumps(dict(unit=dict(name='schedule',version=1),tables=dict(tasks=dict(id=task))))
    path.write_text(before,encoding='utf-8');calls=[]
    class Context:
        def get(self,key):
            calls.append(key)
            assert key not in ('sessions','agentPresets','agents')
            return None
        def emit(self,*args):pass
    facility=DomainFacility(Context(),root_dir=str(tmp_path));domain=await facility.open(schedule_domain)
    try:
        normalized=domain.table('tasks').get('id')
        assert normalized['target']==dict(kind='session',sessionId='old')
        assert normalized['status']=='ended' and path.read_text(encoding='utf-8')==before and calls==['storage']
        original=storage_json.write_atomic
        async def refused(*args):raise OSError('refused')
        monkeypatch.setattr(storage_json,'write_atomic',refused)
        with pytest.raises(OSError,match='refused'):await domain.table('tasks').put('id',dict(normalized,updatedAt=STAMP))
        assert domain.table('tasks').get('id') is normalized and path.read_text(encoding='utf-8')==before
        monkeypatch.setattr(storage_json,'write_atomic',original)
        await domain.table('tasks').put('id',dict(normalized,updatedAt=STAMP))
        saved=json.loads(path.read_text(encoding='utf-8'))
        assert saved['unit']['version']==2 and 'sessionId' not in saved['tables']['tasks']['id']
        with pytest.raises(TypeError):normalized['record']['title']='changed'
    finally:await domain.close()
    domain=await facility.open(schedule_domain)
    try:assert domain.table('tasks').get('id')==parse_schedule_task(saved['tables']['tasks']['id'])
    finally:await domain.close()


def test_schema_detaches_nested_metadata_and_retains_receipt_alias():
    raw=next(entry['task'] for entry in cases() if entry['op']=='parse' and isinstance(entry['task'],dict) and entry['task'].get('target',{}).get('create',{}).get('cwd')=='C:/work')
    task=parse_schedule_task(raw);task['target']['create']['cwd']='changed'
    assert raw['target']['create']['cwd']=='C:/work'
    current=cases()[0]['task'];current=dict(current,sessionId='old',lastDelivery=receipt())
    normalized=parse_schedule_task(current)
    assert normalized['deliveryHistory']['records'][0] is normalized['lastDelivery']


def test_history_pages_and_retention_are_detached_and_read_in_append_order():
    entry=next(entry for entry in cases() if entry['op']=='page' and entry['request']['limit']==3)
    task=parse_schedule_task(entry['task']);saved=copy.deepcopy(task)
    page=delivery_history_page(task,entry['request'],entry['bounds'])
    assert [item['messageId'] for item in page['records']]==['message-6','message-5','message-4']
    page['records'][0]['prompt']='changed';page['retention']['days']=1
    assert task==saved and entry['bounds']['days']==30
    result=append_delivery(task,dict(receipt(7),deliveredAt='2026-09-17T00:01:00.000Z',targetSessionId='new'),dict(days=1,records=2))
    assert [item['messageId'] for item in result['deliveryHistory']['records']]==['message-6','message-7']
    assert result['deliveryHistory']['earlierRecordsUnavailable'] and result['deliveryHistory']['earlierRecordsPruned']
    assert result['deliveryHistory']['records'][-1]['prompt']=='prompt' and task==saved
