import pytest
from scripts.rc022_team_service_probe import observe


@pytest.mark.asyncio
async def test_actual_team_journal_permissions_cas_and_persistence(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert all(row['released'] for row in rows.values())
    for name,row in rows.items():
        if name in ('removed-config','unsafe-config'):
            assert row['error']=='TEAM_INVALID_CONFIG'
        else:
            assert 'error' not in row and row['tails']==0
    workflow=rows['workflow']
    assert workflow['taskEvents']==10 and not workflow['projection']['tasks']
    assert workflow['results'][3]['error']=='TEAM_TASK_BLOCKED'
    assert workflow['results'][5]['error']=='TEAM_TASK_ALREADY_CLAIMED'
    assert workflow['results'][8]['error']=='TEAM_TASK_UNAUTHORIZED'
    claims=rows['concurrent-claims']['results']
    assert claims[2][0]['ownerId']=='a' and claims[2][1]['error']=='TEAM_TASK_STALE_REVISION'
    assert claims[5]['ownerId']=='b'
    assert claims[8]['error']=='TEAM_MEMBER_NOT_FOUND'
    assert rows['dependencies']['results'][3]['error']=='TEAM_TASK_DEPENDENCY_CYCLE'
    assert rows['dependencies']['results'][4]['error']=='TEAM_TASK_HAS_DEPENDENTS'
    for name in ('flush-false','flush-error'):
        row=rows[name]
        assert row['results'][2]['error']=='TEAM_TASK_PERSISTENCE_UNCONFIRMED'
        assert row['results'][3]['revision']==1
        assert row['projection']['tasks'][0]['revision']==2
    assert rows['mode-retry']['modeEvents']==1
    assert rows['default-enabled']['results'][0]['revision']==1
    assert rows['default-enabled']['results'][1]['error']=='TEAM_LEAD_REQUIRED'
    assert rows['stale-queue']['results'][1][1]['error']=='UNAUTHORIZED'
    assert rows['disabled-queue']['results'][1][1]['error']=='TEAM_DISABLED'
    assert rows['stale-queue']['taskEvents']==rows['disabled-queue']['taskEvents']==1
    assert rows['disabled']['results'][4]['error']=='TEAM_DISABLED'
    assert rows['disabled']['results'][-1]['revision']==1
