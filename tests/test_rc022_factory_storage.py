import pytest
from scripts.rc022_factory_storage_probe import observe

@pytest.mark.asyncio
async def test_actual_v4_backend_factory_lifetimes(tmp_path):
    rows=await observe(tmp_path/'factory-storage')
    assert len(rows)==16
    for row in rows:
        assert row['live'] and row['closed'] and row['removed'],row
        if row['action']=='empty':assert not row['exists'];continue
        assert row['exists'] and row['version']==4 and row['inherited']==(2 if row['action']=='inherited' else 0),row
        types=[event['type'] for event in row['stored']]
        assert types[:3]==['turn/start','turn/end','session/end-seed'],row
        assert types.count('session/title')==1,row
        if row['action'] in ('setup-fail','commit-fail','created-fail','queued-fail'):assert row['same'],row
        if row['action']=='queued-fail':
            assert types[-1]=='agent/inbox/spliced' and row['stored'][-1]['data'].get('removedCount',0)==0,row
            assert row['stored'][-1]['data']['inserted'][0]['content'][0]['text']=='retained input',row
        if row['action']=='seed-setup':
            assert row['cold']==row['coldStored'] and row['cold'][:-1]==row['stored'],row
            assert row['cold'][-1]==dict(type='session/end-seed',seq=len(row['stored']),data={}),row
