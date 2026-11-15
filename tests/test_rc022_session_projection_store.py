import pytest

from scripts.rc022_session_projection_store_probe import observe


@pytest.mark.asyncio
async def test_interpreter_registration_belongs_to_the_calling_plugin():
    rows=await observe()
    for row in rows:
        assert row['registered']==['test/project'] and row['sameBorrowed'] and row['snapshotRetained']
        assert row['before']==[[dict(type='text',text='changed')]]*3
        if row['name']=='unrelated':
            assert row['remaining']==['test/project']
            assert row['outcomes']==[['value']*5]*4
        else:
            assert row['remaining']==[]
            assert all('was removed or replaced' in value for outcomes in row['outcomes'] for value in outcomes)
        if row['name']=='duplicate':assert 'already registered' in row['duplicate']
