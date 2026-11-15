import pytest
from scripts.rc022_driver_initiators_probe import observe

@pytest.mark.asyncio
async def test_real_driver_uses_registry_local_initiator_boundaries():
    rows={row['action']:row for row in await observe()}
    for row in rows.values():
        assert row['outside'] and row['idle']
        assert all(entry['after'] for entry in row['observations'])
    assert [entry['id'] for entry in rows['overlap']['observations']]==['left','right']
    assert rows['clear']['observations']==[dict(id='parent',cleared=True,after=True)]
    assert rows['child']['setupParent']=='parent' and rows['child']['setupChild']=='child'
    assert [entry['id'] for entry in rows['child']['observations']]==['child','parent']
