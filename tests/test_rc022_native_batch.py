import pytest
from scripts.rc022_native_batch_probe import observe


@pytest.mark.asyncio
async def test_actual_native_batches_and_durable_partial_failure():
    rows={row['action']:row for row in await observe()}
    for row in rows.values():assert row['drained']
    for key in ('standalone','owned-unlogged','logged','parallel','exclusive','override','conditional'):
        row=rows[key]
        assert [item['value'] for item in row['results']]==['0','1','2']
        assert row['contexts']==['context-0','context-1','context-2']
        assert row['concluded']
        assert row['peak']==(2 if key in ('parallel','override') else 1)
    assert rows['standalone']['events']==rows['owned-unlogged']['events']==[]
    assert len(rows['logged']['events'])==6
    assert [item['value'] for item in rows['cancel-before']['results']]==['ABORTED_BEFORE_DISPATCH']*3
    assert [item['value'] for item in rows['cancel-body']['results']]==['ABORTED','ABORTED_BEFORE_DISPATCH','ABORTED_BEFORE_DISPATCH']
    assert rows['partial']['error']==dict(name='ToolBatchExecutionError',cause=True)
    assert [item['value'] for item in rows['partial']['results']]==['0']
    assert rows['partial']['trace']==[0,1]


@pytest.mark.asyncio
@pytest.mark.parametrize('limit',[0,-1,True,1.5,'2'])
async def test_native_batch_rejects_invalid_override_before_dispatch(limit):
    from dsh.core.tool_calls import execute_tool_batch
    with pytest.raises(ValueError,match='positive integer'):
        await execute_tool_batch(None,dict(maxParallelToolCalls=limit),None,lambda:10)


@pytest.mark.asyncio
async def test_integral_numeric_limit_matches_javascript_number():
    from dsh.core.tool_calls import execute_tool_batch
    from dsh.core.abort import AbortController
    result=await execute_tool_batch(None,dict(maxParallelToolCalls=2.0,calls=[],signal=AbortController().signal),object(),lambda:10)
    assert result==dict(results=[],additionalContexts=[],concluded=False)
