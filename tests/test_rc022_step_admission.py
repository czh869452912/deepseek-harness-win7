import pytest
from scripts.rc022_step_admission_probe import observe


@pytest.mark.asyncio
async def test_actual_step_keeps_and_disposes_its_admission():
    rows={row['action']:row for row in await observe()}
    assert all(row['closed'] for row in rows.values())
    assert rows['enabled']['bodies']==[True]
    assert rows['enabled']['results']==['done']
    assert rows['disabled']['results']==['UNKNOWN_TOOL']
    assert rows['disabled']['requests'][0]['tools']==['plain']
    for key in ('reject','empty','condition-failure','request-failure'):
        assert not rows[key]['requests']
    assert rows['reject']['endings']==['blocked']
    assert rows['empty']['endings']==['completed']
    assert rows['condition-failure']['errors']==[dict(primary=False,code='TOOL_ACTIVATION_FAILED')]
    assert rows['request-failure']['errors']==[dict(primary=True,code=None)]
    assert [request['model'] for request in rows['model-later']['requests']]==['initial','later']
    assert rows['model-later']['requests'][1]['tools']==['plain']
