import asyncio
import pytest
from scripts.rc022_ptc_dispatches_probe import observe


@pytest.mark.asyncio
async def test_nested_pipeline_order_barriers_logging_and_quiescence():
    rows = {row['action']: row for row in await asyncio.wait_for(observe(), 25)}
    assert all(row['drained'] for row in rows.values())
    assert rows['parallel']['peak'] == 2 and rows['reverse']['peak'] == 3
    assert rows['reverse']['orderedCommit']
    assert rows['reverse']['ends'] == [2, 1, 0]
    assert rows['reverse']['post'] == [0, 1, 2]
    assert rows['pre-gate']['serializedPrepare']
    assert rows['post-gate']['barrierThroughPost']
    for action in ('exclusive', 'reclassify'):
        assert rows[action]['exclusiveBarrier']
    assert rows['pre-fails']['starts'] == [1, 2]
    assert rows['deny']['bindings'][0] == dict(error='denied')
    assert rows['post-block']['bindings'][0] == dict(error='blocked')
    assert rows['body-fails']['bindings'][0] == dict(error='body refused')
    assert rows['parallel']['contexts'] == ['post-0', 'body-context', 'post-1', 'post-2']
    assert rows['parallel']['concluded']
    assert rows['log-slow']['logIndependent']
    assert next(e for e in rows['log-fails']['events'] if e['type']=='tool/ptc-dispatch')['data']['content'][0]['text'] == '0'
    assert len(rows['abandon']['events']) == 2
    assert 'tool call abandoned' in rows['abandon']['bindings'][1]['error']
    assert 'call 2 was not dispatched' in rows['limit']['bindings'][1]['error']
    assert all('Error: external cancel' in binding['error'] for binding in rows['external-abort']['bindings'])
