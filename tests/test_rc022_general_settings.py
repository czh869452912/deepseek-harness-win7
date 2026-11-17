import pytest
from scripts.rc022_general_settings_probe import observe


@pytest.mark.asyncio
async def test_live_welcome_acknowledgement_and_settings_cleanup():
    rows=await observe();assert len(rows)==10
    assert [row['value'] for row in rows if row['step']=='value']==[{},dict(welcomeNoticeVersion='v1'),dict(welcomeNoticeVersion='0.2'),{}]
    assert all(row['sameFiber'] for row in rows if row['step']=='value')
    assert [row['accepted'] for row in rows if row['step']=='invalid']==[True,False,False,False]
    assert rows[-1]['calls']==[dict(policy=dict(auto=False),entry='general'),'released']
