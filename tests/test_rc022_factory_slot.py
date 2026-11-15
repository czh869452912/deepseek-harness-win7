import pytest
from scripts.rc022_factory_slot_probe import observe

@pytest.mark.asyncio
async def test_factory_slot_canonicalization_and_call_ownership():
    rows={row['action']:row for row in await observe()}
    assert rows['missing']['create']==rows['missing']['resume']=='no agent factory registered (load an agent-loop plugin)'
    for key in ('plain','traced'):
        row=rows[key]
        assert row['createSame'] and row['resumeSame'] and row['slotRetained']
        assert [call['kind'] for call in row['calls']]==['create','resume']
        assert all(call['request'] and call['owner'] for call in row['calls'])
    assert all(call['canonical'] and call['receiver'] for call in rows['traced']['calls'])
    assert rows['traced']['rawCalls']==['create','resume']
    assert rows['duplicate']['same'] and rows['duplicate']['repeat'] and rows['duplicate']['cleared']
    for key in ('owner-replace','closing-slot'):
        row=rows[key]
        assert row['retained'] and row['cleared'] and row['replacement']
    assert rows['closing-slot']['closingDuplicate']==rows['duplicate']['error']=='an agent factory is already registered'
