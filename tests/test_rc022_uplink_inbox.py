import asyncio
import pytest
from scripts.rc022_uplink_inbox_probe import observe
from dsh.typert.uplink_inbox import UplinkInbox


@pytest.mark.asyncio
async def test_frames_and_single_consumer_queue_boundaries():
    rows=await observe();boxes={row['name']:row for row in rows if 'name'in row}
    assert len(rows)==80
    assert boxes['overflow']['bytes']==0
    assert boxes['overflow']['violations'][0]['code']=='gateway/uplink-overflow'
    assert boxes['after-end']['results'][0]['error']['code']=='gateway/protocol'
    assert boxes['closed-failure']['results']==[dict(done=True),dict(done=True)]
    assert boxes['concurrent-read']['results'][0]['error']['message'].endswith('one pending read')


@pytest.mark.asyncio
async def test_cancelled_python_reader_releases_slot_without_consuming_future_item():
    box=UplinkInbox(8,'fixture',lambda _:None)
    pending=asyncio.create_task(box.__anext__());await asyncio.sleep(0)
    pending.cancel();await asyncio.gather(pending,return_exceptions=True)
    assert box.wake is None
    box.push('next',8)
    assert await box.__anext__()=='next'
    await box.aclose()
