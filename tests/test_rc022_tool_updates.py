import pytest
from scripts.rc022_tool_updates_probe import observe, observe_values


def test_projection_and_historical_fold_preserve_inputs_and_old_snapshots():
    rows=observe_values()
    assert all(row['unchanged'] for row in rows if row['kind']=='project')
    normal=next(row for row in rows if row['kind']=='fold' and row['action']=='normal')
    assert len(normal['snapshots'][-1]['updates'])==3
    assert normal['snapshots'][0]['updates']==[]
    missing=next(row for row in rows if row['kind']=='fold' and row['action']=='missing-definition')
    assert missing['error']=='tool history: missing definition for fetch'
    numeric=next(row for row in rows if row['kind']=='fold' and row['action']=='numeric-keys')
    assert numeric['snapshots'][0] is numeric['snapshots'][1]


@pytest.mark.asyncio
async def test_actual_driver_logs_capability_independent_updates_and_projects_at_dispatch():
    rows=[row for row in await observe() if row['kind']=='driver']
    assert all(row['endings']==['completed']*7 for row in rows)
    assert all(row['restored'] and row['cached'] and not row['errors'] for row in rows)
    for row in rows:
        assert len(row['additions'])==3
        assert row['additions'][0]['bound']==1
        assert row['additions'][1]['bound'] is None
    unsupported,history,addition=rows
    assert unsupported['requests'][1]['updates']==[]
    assert history['requests'][1]['tools'][1]['deferLoading'] is True
    assert history['requests'][2]['tools']==history['requests'][1]['tools']
    assert [tool['name'] for tool in addition['requests'][2]['tools']]==['fetch']
    assert history['requests'][5]['updates']==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['bad',True,{},None])
async def test_invalid_model_tool_update_metadata_is_rejected(mode):
    from dsh.llm.runtime_current import CurrentLLMService
    from dsh.llm.llm_service import LlmError
    with pytest.raises(LlmError,match='invalid tool update mode'):
        CurrentLLMService._normalize_model_info('p','m',dict(provider='p',id='m',name='m',toolUpdate=mode),LlmError)
