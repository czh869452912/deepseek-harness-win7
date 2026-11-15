import pytest

from scripts.rc022_v4_backend_probe import observe


@pytest.mark.asyncio
async def test_v4_backend_owns_migration_and_child_revision_handoff(tmp_path):
    rows=await observe(tmp_path/'backend')
    for row in rows:
        assert 'error' not in row and row['sourceUnchanged'] and row['stages']==row['locks']==0,row
        action=row['action']
        if action=='create':
            assert row['pending']['status'] is None and row['marked']==[True]
            assert row['after']['status']=='current' and row['eventState']=='shared-frozen'
            continue
        assert row['before']['status']=='migration-required' and row['before']['corpus'] and not row['readPublished']
        if action in ('membership-add','membership-remove','child-changed'):
            assert row['publicationError']=='JsonlGenerationSourceChangedError' and row['revisionChanged'],row
            assert row['after']['status']=='migration-required'
        else:
            assert row['published'] and row['after']['status']=='current',row
        if action in ('child-v4','child-v3'):
            assert row['preparedCatalog']==[dict(version=0,childId='child',childCreatedAt=1,mode='continuable',label='worker')]
        elif action=='child-invalid':
            assert row['preparedCatalog']==[dict(version=1,childId='child',childCreatedAt=1,mode='unknown')]
        if action=='unrelated-changed':assert row['revisionChanged']
