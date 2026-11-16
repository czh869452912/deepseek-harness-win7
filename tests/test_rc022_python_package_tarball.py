import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

from dsh.boot.python_package_tarball import downloaded_tarball,unpack_tarball,integrity_options
from dsh.boot.python_plugin_acquisition import verified_record
from dsh.boot import python_plugins as store
from dsh.boot.profile_boot import INSTALL_ANCHOR
from test_python_plugin_distribution import profile,boot,close,echo,EXAMPLE,PACKAGE
from test_python_plugin_acquisition import release_server


def sri(payload,algorithm='sha512'):return algorithm+'-'+base64.b64encode(hashlib.new(algorithm,payload).digest()).decode('ascii')


def archive(path,entries):
    with tarfile.open(str(path),'w:gz',format=tarfile.PAX_FORMAT) as tar:
        for name,payload,kind in entries:
            member=tarfile.TarInfo(name);member.type=kind;member.size=len(payload) if kind==tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):member.linkname='../../escape'
            tar.addfile(member,io.BytesIO(payload) if member.isfile() else None)
    return path


def package_archive(path):
    entries=[('package/'+name,(EXAMPLE/name).read_bytes(),tarfile.REGTYPE) for name in json.loads((EXAMPLE/'package.json').read_text(encoding='utf-8'))['dsh']['release']['files']]
    return archive(path,entries)


@pytest.mark.asyncio
async def test_actual_tls_tarball_install_boot_and_verified_provenance(profile,tmp_path,release_server):
    home,directory=profile;payload=package_archive(tmp_path/'package.tgz').read_bytes();release_server['payload']=payload
    with downloaded_tarball(release_server['url']+'/release?token=fixture-secret',sri(payload)) as (source,record):
        assert record['kind']=='registry-tgz' and '?' not in record['url']
        assert verified_record(source,record)==record
        assert store.install(str(directory),source,INSTALL_ANCHOR,record)==PACKAGE
    assert not Path(source).exists()
    metadata=json.loads((directory/'package.json').read_text(encoding='utf-8'))['dsh']['pythonPlugins'][PACKAGE]
    assert metadata['acquisition']==record
    result=await boot(home)
    try:assert await echo(result['ctx'])=='Python echo: hello'
    finally:await close(result)
    store.uninstall(str(directory),PACKAGE)
    assert not (directory/'node_modules/@example/python-echo').exists()


@pytest.mark.parametrize('failure',['wrong-integrity','strongest-integrity','incomplete','oversized','encoded','range','missing','download-limit','weak-integrity'])
def test_tarball_transfer_refusals_leave_no_payload(tmp_path,release_server,failure):
    payload=package_archive(tmp_path/'package.tgz').read_bytes();release_server['payload']=payload;integrity=sri(payload);endpoint='/asset.zip';options={}
    if failure=='wrong-integrity':integrity=sri(b'other')
    if failure=='strongest-integrity':integrity=sri(payload,'sha256')+' '+sri(b'other','sha512')
    if failure=='weak-integrity':integrity=sri(payload,'sha1')
    if failure in ('incomplete','oversized','encoded','range','missing'):endpoint={'incomplete':'/partial'}.get(failure,'/'+failure)
    if failure=='download-limit':options['max_bytes']=10
    with pytest.raises(ValueError):
        with downloaded_tarball(release_server['url']+endpoint,integrity,**options):pytest.fail('invalid download was yielded')


@pytest.mark.parametrize('name,kind',[
    ('../escape',tarfile.REGTYPE),('package/../escape',tarfile.REGTYPE),('package/C:/escape',tarfile.REGTYPE),
    ('package/con.txt',tarfile.REGTYPE),('package/path\\escape',tarfile.REGTYPE),
    ('package/link',tarfile.SYMTYPE),('package/hard',tarfile.LNKTYPE),('package/fifo',tarfile.FIFOTYPE),('package/dev',tarfile.CHRTYPE),
])
def test_no_tar_paths_or_link_types_can_escape_owned_target(tmp_path,name,kind):
    path=archive(tmp_path/'bad.tgz',[('package/package.json',b'{}',tarfile.REGTYPE),(name,b'bad',kind)]);target=tmp_path/'target';target.mkdir()
    with pytest.raises(ValueError):unpack_tarball(str(path),str(target))
    assert list(target.iterdir())==[] and not (tmp_path/'escape').exists()


@pytest.mark.parametrize('failure',['duplicate','case-collision','too-many','large-member','large-expanded-stream','missing-manifest','nonempty-target','path-conflict','directory-manifest','duplicate-root'])
def test_entire_tar_index_is_checked_before_writing(tmp_path,failure):
    entries=[('package/package.json',b'{}',tarfile.REGTYPE)];options={}
    if failure=='duplicate':entries.append(entries[0])
    if failure=='case-collision':entries.append(('package/PACKAGE.json',b'{}',tarfile.REGTYPE))
    if failure=='too-many':entries.append(('package/other',b'',tarfile.REGTYPE));options['max_files']=1
    if failure=='large-member':entries.append(('package/large',b'x'*30,tarfile.REGTYPE));options['max_bytes']=10
    if failure=='large-expanded-stream':entries.append(('package/large',b'x'*100000,tarfile.REGTYPE));options.update(max_bytes=10,max_files=1)
    if failure=='missing-manifest':entries=[('package/other',b'{}',tarfile.REGTYPE)]
    if failure=='path-conflict':entries.extend([('package/file',b'x',tarfile.REGTYPE),('package/file/nested',b'x',tarfile.REGTYPE)])
    if failure=='directory-manifest':entries=[('package/package.json',b'',tarfile.DIRTYPE)]
    if failure=='duplicate-root':entries.extend([('package',b'',tarfile.DIRTYPE),('package',b'',tarfile.DIRTYPE)])
    path=archive(tmp_path/'bad.tgz',entries);target=tmp_path/'target';target.mkdir()
    if failure=='nonempty-target':(target/'keep').write_bytes(b'user')
    before=sorted(item.name for item in target.iterdir())
    with pytest.raises(ValueError):unpack_tarball(str(path),str(target),**options)
    assert sorted(item.name for item in target.iterdir())==before


def test_record_checks_both_raw_identity_and_selected_integrity(tmp_path):
    path=package_archive(tmp_path/'package.tgz');payload=path.read_bytes()
    record=dict(kind='registry-tgz',url='https://example.invalid/package.tgz',sha256=hashlib.sha256(payload).hexdigest(),bytes=len(payload),integrity=sri(payload))
    assert verified_record(str(path),record)==record
    for modified in [dict(record,integrity=sri(b'other')),dict(record,bytes=True),dict(record,url=record['url']+'?secret=value'),dict(record,sha256='a'*64)]:
        with pytest.raises(ValueError):verified_record(str(path),modified)
    assert integrity_options(sri(payload,'sha256')+' '+sri(payload))[0]=='sha512'


def test_native_cli_accepts_local_tarball_and_never_falls_back_for_missing_tarball(profile,tmp_path,monkeypatch):
    from apps.cli import plugin as cli
    home,directory=profile;path=package_archive(tmp_path/'package.tgz')
    monkeypatch.setattr(cli,'run_pnpm',lambda *args:pytest.fail('native tarball went to pnpm'))
    assert cli.run_plugin('python-test',['add',str(path)])==0
    store.uninstall(str(directory),PACKAGE)
    with pytest.raises(FileNotFoundError):cli.run_plugin('python-test',['add',str(tmp_path/'missing.tgz')])


def test_a_late_completed_tarball_read_cannot_succeed(monkeypatch,release_server):
    from types import SimpleNamespace
    from dsh.boot import python_package_tarball as tarball
    ticks=iter([0,0,2]);monkeypatch.setattr(tarball,'time',SimpleNamespace(monotonic=lambda:next(ticks)))
    with pytest.raises(ValueError,match='exceeded time limit'):
        with downloaded_tarball(release_server['url']+'/asset.zip',sri(release_server['payload']),timeout_seconds=1):pytest.fail('late download accepted')


@pytest.mark.skipif(not os.environ.get('DSH_TEST_PNPM_NODE'),reason='optional pinned Source pnpm pack interoperability')
def test_real_pinned_pnpm_archive_installs_without_node_in_native_store(profile,tmp_path):
    home,directory=profile;source=tmp_path/'author';shutil.copytree(str(EXAMPLE),str(source));manifest=source/'package.json'
    data=json.loads(manifest.read_text(encoding='utf-8'));data['files']=data['dsh']['release']['files'];manifest.write_text(json.dumps(data),encoding='utf-8')
    output=tmp_path/'packed';output.mkdir();command=[os.environ['DSH_TEST_PNPM_NODE'],'--expose-internals',os.environ['DSH_TEST_PNPM_CLI'],'pack','--pack-destination',str(output)]
    result=subprocess.run(command,cwd=str(source),capture_output=True,encoding='utf-8',errors='replace',timeout=30)
    observation=tmp_path/'pnpm-pack.json';observation.write_text(json.dumps(dict(command=command,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)),encoding='utf-8');assert result.returncode==0,result.stderr
    paths=list(output.glob('*.tgz'));assert len(paths)==1
    assert store.install(str(directory),str(paths[0]),INSTALL_ANCHOR)==PACKAGE
    assert (directory/'node_modules/@example/python-echo/python/echo/plugin.py').read_bytes()==(EXAMPLE/'python/echo/plugin.py').read_bytes()
    store.uninstall(str(directory),PACKAGE)
