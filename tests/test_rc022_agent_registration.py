import pytest
from scripts.rc022_agent_registration_probe import observe

@pytest.mark.asyncio
async def test_awaited_agent_registration_and_ordered_disposal():
    rows={row['action']:row for row in await observe()}
    serial=rows['serial']
    assert serial['waiting']==['first:start']
    assert serial['settled']==['first:start','first:end','second','ready'] and serial['live']
    assert serial['disposed']==serial['settled']+['disposed'] and serial['repeat']
    for key in ('sync-reject','async-reject'):
        assert rows[key]['same'] and rows[key]['removed'] and rows[key]['trace'][-1]=='disposed'
        assert 'unreachable' not in rows[key]['trace']
    deferred=rows['detach-await']
    assert deferred['waiting']==['first:start','live'] and not deferred['live']
    assert deferred['settled']==['first:start','live','first:end','second','disposed','ready']
    assert rows['split-stale']['replacement'] and rows['split-stale']['trace']==['disposed']
    assert rows['payload']==dict(action='payload',subject=True,source='compaction',signal=True,keys=['agent','signal','source'])
    assert rows['owner-order']['waiting']==['drain:start'] and rows['owner-order']['liveBefore']
    assert rows['owner-order']['trace']==['drain:start','drain:end','disposed'] and rows['owner-order']['removed']
    assert rows['reentrant-announce']['live']
    assert serial['reentrant']==rows['reentrant-announce']['reentrant']=='agent "agent" was already announced'
    for key in ('effect-repeat','effect-awaited','effect-owner-join'):
        row=rows[key]
        assert row['repeat'] and row['wrapperRepeat'] and row['after']
        assert row['different']==(key=='effect-awaited')
        assert row['trace']==['cleanup:start','cleanup:end']
    assert rows['effect-owner-join']['waiting']
