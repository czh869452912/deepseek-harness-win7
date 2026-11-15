import pytest
from scripts.rc022_projection_handles_probe import observe

@pytest.mark.asyncio
async def test_awaited_registrations_preserve_reader_and_effect_ownership():
    rows={row['action']:row for row in await observe()}
    retained=rows['retained']
    assert retained['before']==dict(init=0,apply=0) and retained['unreadReleased']=={}
    assert retained['retained']==retained['old']==1 and retained['new']==10
    assert retained['checkpoint']==dict(count=dict(ver=2,seq=0,val=10))
    shared=rows['shared']
    assert shared['one']['values']==dict(count=2) and shared['old']==3 and shared['floor'] is None
    assert shared['releasedBefore']['count']['val']==2 and shared['releasedAfter']['count']['val']==3
    assert shared['snapshot']['values']=={}
    lazy=rows['lazy']
    assert lazy['before']['count']['init']==0 and lazy['after']['count']['init']==1
    assert lazy['after']['unrelated']['init']==0 and lazy['bound']==[0,1]
    summary=rows['summary']
    assert summary['sharedStable'] and summary['partialStable'] and summary['invalidated']
    assert summary['keys']==[] and summary['calls']['host']['init']==summary['calls']['excluded']['init']==0
    assert len(rows['conflicts']['errors'])==6
    for action in ('return','effect','yield'):
        assert rows[action]['before']['values']==dict(count=0)
        assert rows[action]['after']['values']=={} and rows[action]['retained']==1
    assert rows['legacy']['value']==1 and rows['legacy']['snapshot']['values']=={}
    assert rows['drive']['events']==[[[dict(key='count',val=1),dict(key='second',val=1)],0]]
    for action in ('unit-failure','listener-failure'):
        assert rows[action]['events']==[[[dict(key='count',val=1)],0]]
    assert 'inactive context' in rows['handoff']['error'] and 'exposed' not in rows['handoff']
    assert rows['mutated']['before']==5 and rows['mutated']['after']['values']['mutable']==30
    assert rows['reader-failure']['same'] and rows['reader-failure']['before']['init']==0
    assert rows['undefined']['undefined'] and rows['undefined']['value']==1
    assert rows['double-release']['before']['values']==dict(count=1) and rows['double-release']['after']['values']=={}
