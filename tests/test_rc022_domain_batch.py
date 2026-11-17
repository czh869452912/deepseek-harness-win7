import json

import pytest

from dsh.storage.domain_impl import DomainFacility
from dsh.storage.domain_spec import define_domain,domain_table
from dsh.storage import storage_json
from scripts.rc022_domain_batch_probe import observe


@pytest.mark.asyncio
async def test_domain_batch_fifo_and_quarantine_observations(tmp_path):
    rows=await observe();(tmp_path/'domain-batch-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==15
    poisoned=[row for row in rows if row['case']['failure']=='unknown-state' and row['case']['keys'] not in ([],['missing'])]
    assert len(poisoned)==2
    for row in poisoned:
        assert all(value['error']==dict(code='unknown-state',same=True) for value in row['reads'].values())
        assert row['following']['error']==dict(code='unknown-state',same=True)
        assert row['afterClose']=='closed' and row['closed']==['unit','domain']
    successful=next(row for row in rows if row['case']==dict(keys=['a','c','a','missing'],failure=None,throwObserver=False))
    assert successful['deleted']==dict(value=2)
    assert [event['view'] for event in successful['events'][:2]]==[dict(b=2),dict(b=2)]


@pytest.mark.asyncio
async def test_real_json_batch_is_one_atomic_publication_and_cold_reopens(tmp_path,monkeypatch):
    facility=DomainFacility(None,root_dir=str(tmp_path));spec=define_domain(name='shape',version=1,tables=dict(t=domain_table(lambda value:value)))
    domain=await facility.open(spec);table=domain.table('t')
    await table.put('a',1);await table.put('b',2);await table.put('c',3)
    original=storage_json.write_atomic;calls=[]
    async def publish(path,text):calls.append(json.loads(text));await original(path,text)
    monkeypatch.setattr(storage_json,'write_atomic',publish)
    assert await table.deleteMany(['missing','a','c','a'])==2
    assert len(calls)==1 and calls[0]['tables']['t']==dict(b=2)
    assert await table.deleteMany(['missing'])==0 and len(calls)==1
    await domain.close();domain=await facility.open(spec)
    try:assert dict(domain.table('t').entries())==dict(b=2)
    finally:await domain.close()
