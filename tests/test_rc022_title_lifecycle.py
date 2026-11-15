import pytest
from scripts.rc022_title_lifecycle_probe import observe

@pytest.mark.asyncio
async def test_title_work_cancels_without_accepting_late_results_and_drains():
    rows=await observe()
    assert len(rows)==6
    for row in rows:
        assert row['released']==[False,False]
        if row['action']=='overlap':assert row['title']['title']=='Newer' and row['aborted']
        elif row['action']=='caller-cancel':assert row['sameReason'] and row['title']['source']['kind']=='fallback'
        elif row['action']=='session-detach':assert 'session disposed' in row['error']
        elif row['action']=='service-drain':assert row['draining'] and row['error']=='session-title service disposed'
        elif row['action']=='queued-dispose':assert row['title'] is None and row['titleEvents']==[]
        elif row['action']=='empty-fallback':assert row['requests'][0]['currentTitle'] is None and len(row['titleEvents'])==1
