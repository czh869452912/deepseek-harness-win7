import pytest
from scripts.rc022_factory_publication_probe import observe

@pytest.mark.asyncio
async def test_factory_publication_maintenance_and_cancellation_barriers():
    rows={row['action']:row for row in await observe()}
    for row in rows.values():
        assert row['idle'] and row['removed']
        assert row['trace'][0]==dict(stage='session',session=True,agent=False,turns=0)
        assert row['trace'][1]==dict(stage='setup',session=True,agent=False,turns=0)
        for entry in row['trace']:
            if entry['stage'] in ('created','created-end'):assert entry==dict(stage=entry['stage'],session=True,agent=True,turns=0)
    for action in ('setup-reject','created-reject','caller-setup'):
        row=rows[action]
        assert row['rejected'] and row['same'] and row['pending']==['queued'] and row['turns']==0
        assert all(call['keep'] for call in row['cancels'])
    for action in ('setup-wake','created-wake','caller-ready'):
        row=rows[action]
        assert row['messages']==['after-ready' if action=='caller-ready' else 'queued'] and row['turns']==1 and row['pending']==[]
    assert rows['owner-created']['waiting'] and rows['owner-created']['rejected']
    assert rows['owner-created']['pending']==['queued'] and rows['owner-created']['turns']==0
    assert [entry['stage'] for entry in rows['commit']['trace']][:4]==['session','setup','commit','created']
    assert all(rows['clear-failure'][key] for key in ('cancelSame','disposeSame','cancelled','waiting'))
    assert rows['clear-failure']['turns']==0 and rows['clear-failure']['pending']==['queued']
