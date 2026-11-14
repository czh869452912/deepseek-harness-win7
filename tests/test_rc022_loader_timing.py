import asyncio
from scripts import rc022_loader_timing_probe as probe


def test_mutation_prefixes_and_parent_owned_teardown():
    result=asyncio.run(probe.native())
    for mode in ('remove','stop'):
        state=result[mode]
        assert not state['registered'] and state['retained'] and state['disposed']
        assert state['partials']==[['a',False]]
        assert state['cleanup_pending'] and state['shutdown_pending'] and state['cleaned']==[True]
        assert not state['disabled']
    assert result['remove']['rows']==0 and result['remove']['commits']==['a','-a']
    assert result['stop']['rows']==1 and result['stop']['commits']==['a']
    assert result['replace']==dict(published=True,partials=[['a',True]],empty_pending=False,empty_store=[],calls=[1,2])
    assert result['import']==dict(prefix=['import'],pending=True,registered=True,calls=['import',1])
    assert result['concurrent-import']==result['import']
