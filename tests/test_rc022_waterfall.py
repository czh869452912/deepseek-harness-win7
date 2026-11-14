import asyncio
from scripts import rc022_waterfall_probe as probe


def test_final_thunk_veto_original_arguments_and_eager_async_prefix():
    result=asyncio.run(probe.native())
    assert result['inner']==[] and result['listener_args']==[['a',1],['a',1]]
    for mode in ('no-inner','seed-only','non-callable'):assert result[mode]=='TypeError'
    assert result['veto']=='veto' and result['named_next']=='original'
    assert result['prefix']==['outer-before','inner-before','outer-next-returned']
    assert result['async_result']=='end!'
    assert result['trace']==result['prefix']+['inner-after','outer-after']
    assert result['await_sync']==42 and result['await_sync_trace']==['before','inner','next-returned','after']
