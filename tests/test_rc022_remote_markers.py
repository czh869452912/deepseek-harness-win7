import pytest
from scripts.rc022_remote_markers_probe import observe
from dsh.typert.remote import Remote, RemoteScope, remote_methods


@pytest.mark.asyncio
async def test_resource_declarations_and_principal_identity():
    rows=await observe()
    assert rows[1]['read']==['a','b'] and rows[1]['frozen']
    assert rows[2]['read']=='scope' and rows[2]['frozen']
    assert rows[3]['snapshotSafe']
    assert rows[-5]['inherited']==['inherited','child']
    assert rows[-2]['principal']==dict(kind='guest',id='g')
    assert rows[-1]['principal']==dict(kind='Owner')


def test_distinct_reader_declarations_conflict_and_reused_decorator_is_idempotent():
    def method(self, value):pass
    decorator=Remote(dict(resources=dict(session=lambda value:value)))
    decorator(method);decorator(method)
    with pytest.raises(ValueError,match='conflicting'):
        Remote(dict(resources=dict(session=lambda value:value)))(method)


def test_alias_and_scoped_reader_resources_remain_snapshot_protected():
    class Service:
        @RemoteScope('agent',dict(name='alias',resources=dict(session=lambda value:value)))
        def original(self, value):pass
    service=Service();marker=remote_methods(service)[0]
    assert marker['exportName']=='alias'
    marker['invocation']['context']='mutated'
    assert remote_methods(service)[0]['invocation']==dict(kind='context',context='agent')
