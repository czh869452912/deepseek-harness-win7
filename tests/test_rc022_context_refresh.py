import pytest
from scripts.rc022_context_refresh_probe import observe


@pytest.mark.asyncio
async def test_context_refresh_snapshots_and_actual_requests():
    rows={row['action']:row for row in await observe()}
    for key in ('refresh','suppressed','required-missing','removed','literal'):
        assert rows[key]['same']==[True]*3
        assert rows[key]['counts']==dict(sections=1,tools=1,variables=1,assemblies=1)
        assert rows[key]['tools'][0]['name']=='fixed'
    assert rows['suppressed']['contexts']==[dict(name='live',text='after {{literal}}',interpolate=False)]
    assert rows['runtime-normal']['unchanged']
    assert len(rows['runtime-normal']['messages'])==3
    assert '<\\/SYSTEM-reminder >' in rows['runtime-escape']['messages'][0]['content'][0]['text']
    for key in ('refresh','suppress','retry'):
        row=rows['driver-'+key]
        assert row['endings']==['completed']
        assert row['state']['assemblies']==row['state']['conditions']==1
        assert row['requests'][0][-1]['source']['sections'][0]['text']=='attempt-1'
    assert len(rows['driver-suppress']['requests'][0][0]['source']['sections'])==1
    assert rows['driver-retry']['state']['attempts']==2
    assert rows['driver-retry']['requests'][1][-1]['source']['sections'][0]['text']=='attempt-2'
