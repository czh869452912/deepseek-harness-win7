import asyncio
from pathlib import Path

import pytest

from dsh.fs.local_current import CurrentFileSystem
from dsh.fs.fs_local import FsError
from dsh.fs.patch import parse_patch
from scripts import rc022_fs_mutations_probe as probe


def hunks(before,after):return parse_patch('*** Begin Patch\n*** Update File: a\n@@\n-'+before+'\n+'+after+'\n*** End Patch')[0]['hunks']


@pytest.mark.asyncio
async def test_actual_mutations_extra_grants_and_all_fences(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await probe.observe()}
    assert rows['patch-extra']['value']['after']=='ONE\nTWO\n'
    assert rows['patch-bytes']['value']=='ONE\r\nTWO\r\n'
    assert rows['stale-patch']['error']['code']=='FS_STALE_VERSION'
    assert rows['mismatch']['error']['code']=='FS_PATCH_MISMATCH'
    assert rows['delete-extra']['value']['before']=='ONE\nTWO\n' and not rows['deleted']['exists']
    assert rows['moved-bytes']==dict(name='moved-bytes',source=False,destination='new\r\n')
    assert rows['blind-move-refused']['error']['code']=='FS_NOT_OBSERVED'
    assert rows['partial-move']['value']['destination']['operation']=='update'
    assert not rows['partial-move']['value']['sourceDeleted']
    assert rows['partial-move']['value']['sourceFailure']['code']=='FS_PERMISSION_DENIED'
    assert rows['abort-before-move']['error']['code']=='FS_ABORTED'
    assert rows['abort-after-checkpoint']['value']['sourceDeleted']
    assert rows['checkpoint-effects']['aborted'] and not rows['checkpoint-effects']['source']
    assert rows['binary-delete']['value']['before'] is None
    assert all(rows['readonly-'+verb]['error']['code']=='FS_SANDBOX_DENIED' for verb in ('write','edit','patch','delete','move'))
    assert rows['revoked-grant']['error']['code']=='FS_SANDBOX_DENIED' and rows['held-effect']['value']=='held'
    assert rows['invalid-extra-before-workspace-write']['error']['code']=='SANDBOX_INVALID_ROOT'
    assert rows['junction-existing-denied']['error']['code']=='FS_SANDBOX_DENIED'
    assert rows['junction-new-denied']['error']['code']=='FS_SANDBOX_DENIED'
    assert rows['replaced-extra-denied']['error']['code']=='SANDBOX_INVALID_ROOT'
    assert rows['junction-effects']==dict(name='junction-effects',existing='keep',new=False)
    assert rows['locks-released']['value']


@pytest.mark.asyncio
async def test_opposing_moves_and_single_target_mutations_share_lock_order(tmp_path):
    fs=CurrentFileSystem(cwd=str(tmp_path));a=await fs.resolve('a');b=await fs.resolve('b')
    await fs.writeText(a,'A\n');await fs.writeText(b,'B\n')
    first=fs.moveFile(a,b,{});second=fs.moveFile(b,a,{})
    results=await asyncio.wait_for(asyncio.gather(first,second),5)
    assert all(result.sourceDeleted for result in results)
    assert (tmp_path/'a').read_text(encoding='utf-8')=='A\n' and not (tmp_path/'b').exists()
    moving=fs.moveFile(a,b,{});writing=asyncio.create_task(fs.writeText(a,'new'))
    await asyncio.wait_for(asyncio.gather(moving,writing),5)
    assert (tmp_path/'a').read_text(encoding='utf-8')=='new' and (tmp_path/'b').read_text(encoding='utf-8')=='A\n'
    assert not fs._locks and not fs._lock_users


@pytest.mark.asyncio
async def test_cancelled_move_waiter_does_not_interrupt_owned_publication_and_source_removal(tmp_path):
    fs=CurrentFileSystem(cwd=str(tmp_path));source=await fs.resolve('source');destination=await fs.resolve('destination');await fs.writeText(source,'content')
    entered=asyncio.get_running_loop().create_future();gate=asyncio.get_running_loop().create_future()
    async def inspect(_):
        entered.set_result(None);await gate
    fs.internals.inspectTemp=inspect;operation=fs.moveFile(source,destination,{})
    async def wait():return await operation
    waiter=asyncio.create_task(wait());await asyncio.wait_for(entered,5);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    gate.set_result(None);result=await asyncio.wait_for(operation,5)
    assert result.sourceDeleted and not (tmp_path/'source').exists()
    assert (tmp_path/'destination').read_text(encoding='utf-8')=='content'
    assert not fs._locks and not list(tmp_path.glob('*.tmpdir'))


@pytest.mark.asyncio
async def test_guard_checked_after_queueing_before_matching(tmp_path):
    fs=CurrentFileSystem(cwd=str(tmp_path));target=await fs.resolve('file');await fs.writeText(target,'A\n');version=(await fs.stat(target)).version
    first=fs.patchText(target,hunks('A','B'),dict(version=version));second=fs.patchText(target,hunks('A','C'),dict(version=version))
    result=await first;assert result.after=='B\n'
    with pytest.raises(FsError) as error:await second
    assert error.value.code=='FS_STALE_VERSION' and not fs._locks


@pytest.mark.asyncio
async def test_directory_substitution_is_never_recursively_removed(tmp_path):
    fs=CurrentFileSystem(cwd=str(tmp_path));target=await fs.resolve('file');await fs.writeText(target,'before')
    def replace(_):
        path=Path(target.targetKey);path.unlink();path.mkdir();(path/'user-data').write_text('keep',encoding='utf-8')
    fs.internals.inspectBeforeMutation=replace
    with pytest.raises(FsError) as error:await fs.deleteFile(target)
    assert error.value.code=='FS_IO_ERROR'
    assert (tmp_path/'file/user-data').read_text(encoding='utf-8')=='keep' and not fs._locks


@pytest.mark.asyncio
async def test_moving_to_new_destination_does_not_copy_acl_from_absent_target(tmp_path):
    fs=CurrentFileSystem(cwd=str(tmp_path));source=await fs.resolve('source');destination=await fs.resolve('destination');await fs.writeText(source,'source')
    copies=[];fs.internals.platform='win32';fs.internals.copyFileDacl=lambda source,target:copies.append((source,target))
    result=await fs.moveFile(source,destination,dict(expectedDestination=dict(kind='createIfAbsent')))
    assert result.sourceDeleted and copies==[]
    # An existing destination retains its own ACL, independently of source mode.
    await fs.writeText(source,'again');copies.clear()
    result=await fs.moveFile(source,destination,{})
    assert result.sourceDeleted and len(copies)==1 and copies[0][0]==destination.targetKey
