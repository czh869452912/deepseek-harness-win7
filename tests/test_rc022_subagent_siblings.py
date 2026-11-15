import pytest
from scripts.rc022_subagent_siblings_probe import observe


@pytest.mark.asyncio
async def test_actual_public_cross_branch_and_cold_target_contracts(tmp_path):
    rows={row['action']:row for row in await observe(tmp_path)}
    assert all(not row['resident'] and row['slots']==0 and row['reservations']==0 for row in rows.values())
    live=rows['live']
    assert live['accepted'] and live['self']==live['interrupt']=='UNAUTHORIZED'
    assert [(item['target'],item['sender']) for item in live['received']]==[('leaf','a'),('leaf','root'),('root','leaf')]
    assert live['received'][-1]['text']=='Agent b/leaf sent a message: grandparent'
    cold=rows['cold-creator']
    assert cold['accepted'] and not cold['creatorLive'] and cold['beforeDrain']==['a','leaf']
    assert cold['resumedNames']==dict(self='b/leaf',parent='b')
    assert rows['provider-removed']['accepted']
    for action in ('sender-stale','root-replaced','outside'):
        assert rows[action]['error']=='UNAUTHORIZED' and not rows[action]['received']
    assert rows['unreadable']['error']=='NOT_RESUMABLE' and rows['unreadable']['beforeDrain']==['a']
    assert rows['capacity']['error']=='ACTIVATION_LIMIT_REACHED'
    assert [item['target'] for item in rows['capacity']['received']]==['b']
    assert rows['parent-direct']['omitClosing']
