import sys

import pytest

from dsh.sandbox.policy_current import SandboxInvalidRootError
from dsh.sandbox.roots_current import workspace_writable_roots,writable_roots
from scripts import rc022_writable_roots_probe as probe


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform!='win32',reason='Actual Windows junction, casing and separator fixtures')
async def test_actual_physical_roots_and_alias_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await probe.observe()}
    assert rows['canonical']['alias']=='<root>\\Memory'
    assert rows['extras']['workspace']==['<root>\\workspace','<root>\\Memory']
    assert rows['case-and-separator']['workspace']==rows['extras']['workspace']
    assert rows['workspace-duplicate']['workspace']==['<root>\\workspace']
    for name in ('missing','file','junction'):assert rows[name]['error']['code']=='SANDBOX_INVALID_ROOT'
    assert rows['readonly-invalid']['all']==[] and rows['full-invalid']['workspace']==[]
    assert rows['revalidate']['code']=='SANDBOX_INVALID_ROOT'


@pytest.mark.skipif(sys.platform!='win32',reason='Windows junction swap does not require symbolic link privilege')
def test_previously_valid_grant_rejects_replaced_directory_without_granting_target(tmp_path):
    import _winapi
    extra=tmp_path/'extra';other=tmp_path/'other';extra.mkdir();other.mkdir()
    policy=dict(mode='workspace-write',workspaceRoot=str(tmp_path/'workspace'),additionalWritableRoots=[str(extra)])
    before=workspace_writable_roots(policy);extra.rmdir();_winapi.CreateJunction(str(other),str(extra))
    try:
        with pytest.raises(SandboxInvalidRootError,match='symlinked grants are not supported'):workspace_writable_roots(policy)
        assert str(other) not in before
    finally:extra.rmdir()
    assert other.is_dir()


@pytest.mark.parametrize('mode',['read-only','danger-full-access'])
def test_non_workspace_modes_do_not_validate_or_grant_explicit_roots(mode,tmp_path):
    policy=dict(mode=mode,workspaceRoot=str(tmp_path),additionalWritableRoots=[str(tmp_path/'missing'),'bad\0root'])
    assert workspace_writable_roots(policy)==[] and writable_roots(policy)==[]


def test_new_missing_or_unreadable_extra_root_never_becomes_workspace_fallback(tmp_path):
    workspace=tmp_path/'missing-workspace';file=tmp_path/'file';file.write_text('content',encoding='utf-8')
    assert workspace_writable_roots(dict(mode='workspace-write',workspaceRoot=str(workspace)))==[str(workspace)]
    for extra in (str(file),str(tmp_path/'missing-extra'),'bad\0root'):
        with pytest.raises(SandboxInvalidRootError) as error:workspace_writable_roots(dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[extra]))
        assert error.value.code=='SANDBOX_INVALID_ROOT'
