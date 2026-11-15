import pytest
from scripts.rc022_pipeline_source_probe import observe


@pytest.mark.asyncio
async def test_executor_private_pipeline_and_cancellation_keep_their_contract():
    rows={row['action']:row for row in await observe()}
    assert all(not row['registry'] for row in rows.values())
    assert all(all(value['agent'] and value['admission'] for value in row['lookups']) for row in rows.values())
    assert rows['virtual']['value']=='ok'
    assert rows['virtual']['schemaSame'] and rows['nested']['schemaSame']
    assert rows['post-value']['value']=='replacement'
    assert rows['refuse']['trace']==['result']
    assert rows['refuse']['error']['info']['code']=='UNKNOWN_TOOL'
    assert rows['refuse-aborted']['trace']==['final','result']
    assert rows['refuse-aborted']['error']['info']['code']=='ABORTED_BEFORE_DISPATCH'
    assert rows['unknown']['trace']==['pre','post','result']
    assert rows['disappeared']['trace']==['pre','project','post','final','result']
    assert rows['classifier']['mode']=='parallel'
    for name in ('abort-reason','abort-name'):
        assert rows[name]['error']['info']==dict(name='AbortError',code='ABORTED')
    assert rows['abort-identity']['error']['info']['code']=='OWN_FAILURE'
    assert 'info' not in rows['abort-other']['error']
