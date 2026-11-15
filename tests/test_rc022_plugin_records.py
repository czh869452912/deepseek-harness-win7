import pytest

from scripts.rc022_plugin_records_probe import observe


@pytest.mark.asyncio
async def test_records_are_ignorable_durable_and_owned():
    rows={row['name']:row for row in await observe()}
    assert rows['plugin:a']['seq']==1 and rows['plugin:a']['record'] and rows['plugin:a']['identical']
    assert rows['plugin:a']['nodes']==[]
    for name in ('plugin:','plugin:Test/state','plugin:test/','plugin:a\n','plugin:a\r','plugin:a\u2028'):
        assert rows[name]['seq']==0 and 'must be "plugin:"' in rows[name]['error']
    durable=rows['durable'];assert durable['returned']==1 and durable['identical'] and all(durable['notRecord'])
    assert durable['data']==dict(count=1,nested=['a',2]) and durable['copies']==[durable['data']]*3
    assert durable['nodes']==[0] and durable['messages']==[[dict(type='text',text='hello')]]*4
    for name in ('nan','infinity','negative-zero','undefined'):
        assert rows[name]['seq']==0 and 'non-JSON-serializable data' in rows[name]['error']
    for action in ('normal','failed','veto','reentry','detach'):
        row=rows['ownership-'+action]
        assert 'outside a SessionStore' in row['stages'][0]
        assert all('before session/created completes' in value for value in row['stages'][1:3])
        assert 'outside a SessionStore' in row['stale'] and not row['live'] and row['replacement']==0
    assert rows['ownership-normal']['stages'][3]==0
    assert rows['ownership-failed']['seq']==rows['ownership-veto']['seq']==0
    assert rows['ownership-veto']['heard']==[]
    assert 'cannot reenter' in rows['ownership-reentry']['reentry'][0]
    assert rows['ownership-detach']['heard']==[dict(type='plugin:test/state',seq=0,size=1,record=True)]
