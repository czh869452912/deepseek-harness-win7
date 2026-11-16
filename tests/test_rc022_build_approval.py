import pytest
from dsh.boot.plugin_build_approval import record_pending_builds,approve_builds,blocked_build_names
from scripts.rc022_build_approval_probe import observe


@pytest.mark.asyncio
async def test_build_permissions_are_explicit_and_atomic_over_policy_forms(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==42
    assert rows['policy-0']['recorded']['value']==['native@1.0.0','@scope/other@file:../other']
    assert rows['policy-0']['pending']['value']==['@scope/other@file:../other']
    assert rows['policy-4']['comments'] and rows['policy-4']['unrelated']
    assert not rows['approve-missing']['approvedChanged']
    assert rows['approve-missing']['approved']==dict(error='stale-approval')
    for index in (7,8,9,10,11,12,13,14,15):
        assert 'error' in rows['policy-'+str(index)]['recorded']
        assert not rows['policy-'+str(index)]['recordedChanged']
    for index in (1,2,3):
        assert not rows['git-'+str(index)+'-1']['exists']
    assert rows['report-3']['recorded']['value']==['native','native','other']


@pytest.mark.asyncio
async def test_approval_preserves_other_permissions_without_running_code(tmp_path):
    path=tmp_path/'pnpm-workspace.yaml'
    original='# settings\nother: &unrelated value\ncopy: *unrelated\nallowBuilds:\n  native: set this to true or false # keep\n  denied: false\n'
    path.write_text(original,encoding='utf-8')
    await approve_builds(str(tmp_path),['native'])
    assert path.read_text(encoding='utf-8')==original.replace('set this to true or false','true')
    assert await record_pending_builds(str(tmp_path),'')==[]
    assert blocked_build_names('Ignored build scripts: @scope/*, x@?')==[]
