import pytest
from scripts.rc022_activation_result_probe import observe


@pytest.mark.asyncio
async def test_capacity_locks_and_epoch_results():
    rows=await observe()
    assert rows[0]['code']=='ACTIVATION_LIMIT_REACHED'
    assert rows[2]['remaining']==0
    assert rows[3]==dict(kind='locks',trace=['first','other','failed','second'],first='first failure',second=2,other=3,remaining=0)
    captured=[row for row in rows if row['kind']=='capture']
    assert captured[0]['value']==dict(output=[dict(type='text',text='answer')],stopReason='completed')
    assert captured[1]['value']['stopReason']=='error'
    assert captured[2]['value']['structured'] is None
    for row in rows:
        if row['kind']=='notice':
            assert row['value']['source']['stopReason']==row['reason']
            assert all(block['type']=='text' for block in row['value']['content'])
        if row['kind']=='failure':assert row['value']['stopReason']=='error'
