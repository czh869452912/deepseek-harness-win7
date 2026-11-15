import pytest

from scripts.rc022_session_append_probe import observe


@pytest.mark.asyncio
async def test_batch_is_atomic_and_observers_receive_the_final_surface():
    rows={row['name']:row for row in await observe()}
    for name in ('invalid-surface','project-reject','developer-invalid','empty-member','dispatch-veto'):
        assert rows[name]['seq']==0 and rows[name]['nodes']==[] and rows[name]['observed']==[]
        assert 'error' in rows[name]
    for name in ('simple','replace','project','developer','reentrant','detach','listener-change'):
        row=rows[name]
        assert row['returned']==[0,1] and row['publicationCleared']
        assert all(item['length']==2 and item['member'] and item['live'] for item in row['observed'][:2])
    assert rows['replace']['nodes']==[1]
    assert rows['project']['messages']==[[dict(type='text',text='projected')]]
    assert len(rows['reentrant']['reentry'])==2
    assert rows['listener-change']['extra']==[2]
    assert not rows['detach']['live'] and 'outside a SessionStore' in rows['detach']['afterDetach']
    for name in ('normal','failed','detach-created'):
        row=rows['membership-'+name]
        assert 'outside a SessionStore' in row['stages'][0]
        assert all('before session/created completes' in value for value in row['stages'][1:3])
        assert 'outside a SessionStore' in row['old'] and row['replacement']==0
    assert rows['membership-normal']['stages'][3]=='value'
    assert 'before session/created completes' in rows['membership-failed']['stages'][3]
