import asyncio
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
import stat

import pytest

from dsh.host import workspace_runtime_files_current as runtime
from scripts.rc022_workspace_files_probe import observe,SCENARIOS


@pytest.mark.asyncio
async def test_actual_runtime_install_recovery_and_links(tmp_path):
    rows=await observe(tmp_path/'files')
    (tmp_path/'workspace-files-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(SCENARIOS)==20
    by={row['scenario']:row for row in rows}
    for row in rows:
        assert row['outside']=={'keep':'outside'}
        assert row['staging']==[]
    for name in ['resolve','install','reuse','digest','recover','package-order','unknown-fields','payload-link','old-previous']:
        assert by[name]['error'] is None
    for name in ['reuse','recover','unknown-fields']:assert by[name]['root']['user-package']=='user'
    for name in ['digest','package-order']:assert 'user-package' not in by[name]['root']
    for name in ['incomplete','recovery-incomplete']:assert by[name]['error']=={'code':'ENOENT'} and by[name]['root']['user-package']=='user'
    for name in ['root-link','previous-link','manifest-link']:assert 'filesystem link' in by[name]['error']['message']
    assert by['payload-link']['root']['extra']=={'keep':'outside'}


@pytest.mark.asyncio
async def test_public_filesystem_work_survives_cancelled_awaiter(monkeypatch,tmp_path):
    entered=threading.Event();release=threading.Event();finished=[]
    def blocked(source):entered.set();release.wait(10);finished.append(source);return {'prepared':source}
    monkeypatch.setattr(runtime,'_resolve',blocked)
    operation=runtime.resolvePrimaryRuntime('fixture')
    async def wait():return await operation
    waiter=asyncio.create_task(wait())
    try:
        assert await asyncio.get_running_loop().run_in_executor(None,entered.wait,5)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):await waiter
        assert not operation.task.done()
    finally:release.set()
    assert await operation=={'prepared':'fixture'} and finished==['fixture']


@pytest.mark.asyncio
@pytest.mark.parametrize('replacing',[False,True])
async def test_failed_publication_rolls_back_and_removes_staging(tmp_path,monkeypatch,replacing):
    # Reuse the same real carrier fixture, then inject only the final rename failure.
    await observe(tmp_path/'setup')
    source=tmp_path/'setup'/'install'/'source';root=tmp_path/'root'
    if replacing:
        await runtime.installPrimaryRuntime(str(source),str(root));(root/'keep').write_text('old',encoding='utf-8')
        value=json.loads((source/'runtime.json').read_text(encoding='utf-8'));value['payloadDigest']='b'*64
        (source/'runtime.json').write_text(json.dumps(value),encoding='utf-8')
    rename=os.rename
    def failing(left,right):
        if Path(left).name.startswith('.primary-runtime-') and Path(right)==root:raise PermissionError('publication locked')
        return rename(left,right)
    monkeypatch.setattr(runtime.os,'rename',failing)
    with pytest.raises(PermissionError,match='publication locked'):await runtime.installPrimaryRuntime(str(source),str(root))
    assert not list(tmp_path.glob('.primary-runtime-*')) and not Path(str(root)+'.previous').exists()
    assert (root/'keep').read_text(encoding='utf-8')=='old' if replacing else not root.exists()


def test_alias_validation_and_read_errors_with_controlled_fs(monkeypatch):
    manifest={'platform':'linux','python':'3.8.10'};regular=SimpleNamespace(st_mode=stat.S_IFREG)
    link=SimpleNamespace(st_mode=stat.S_IFLNK)
    monkeypatch.setattr(runtime.os,'lstat',lambda path:regular if path.endswith('python3.8') else link)
    monkeypatch.setattr(runtime.os,'readlink',lambda path:'python3.8')
    assert runtime._aliases('fixture',manifest)=={'dependencies/python/bin/python':'python3.8','dependencies/python/bin/python3':'python3.8'}
    monkeypatch.setattr(runtime.os,'readlink',lambda path:'./python3.8')
    with pytest.raises(ValueError,match='invalid Python alias'):runtime._aliases('fixture',manifest)
    monkeypatch.setattr(runtime.os,'lstat',lambda path:(_ for _ in ()).throw(PermissionError('denied')))
    with pytest.raises(PermissionError,match='denied'):runtime._aliases('fixture',manifest)
    assert runtime._aliases('fixture',dict(manifest,platform='win32'))=={}


def test_copy_recreates_only_selected_relative_aliases(tmp_path,monkeypatch):
    source=tmp_path/'source';destination=tmp_path/'destination';binary=source/'dependencies'/'python'/'bin'
    binary.mkdir(parents=True);(binary/'python3.8').write_bytes(b'interpreter')
    for name in ['python','python3']:(binary/name).write_bytes(b'alias-placeholder')
    aliases={'dependencies/python/bin/'+name:'python3.8' for name in ['python','python3']}
    monkeypatch.setattr(runtime,'_aliases',lambda root,manifest:aliases)
    created=[]
    def symlink(target,path):
        assert not Path(path).exists();created.append((target,Path(path).relative_to(destination).as_posix()))
    monkeypatch.setattr(runtime.os,'symlink',symlink)
    runtime._copy(str(source),str(destination),{'platform':'linux','python':'3.8.10'})
    assert (destination/'dependencies'/'python'/'bin'/'python3.8').read_bytes()==b'interpreter'
    assert created==[('python3.8',path) for path in aliases]
