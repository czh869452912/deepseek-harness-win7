import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from scripts.build_desktop import extract_tool, nsis_define
from scripts import build_desktop

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', ['../escape', 'C:/escape', 'directory/../../escape'])
def test_tool_archive_cannot_escape_owned_output(tmp_path, name):
    archive = tmp_path / 'tool.zip'
    with zipfile.ZipFile(str(archive), 'w') as stream:
        stream.writestr(name, b'not executable')
    identity = dict(bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='Unsafe'):
        extract_tool(archive, identity, tmp_path / 'unpacked')


def test_tool_archive_must_match_fixed_bytes(tmp_path):
    archive = tmp_path / 'tool.zip'
    archive.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='SHA256'):
        extract_tool(archive, dict(bytes=9,sha256='0'*64), tmp_path / 'unpacked')
    assert not (tmp_path / 'unpacked').exists()


def test_nsis_define_preserves_literal_dollar_and_rejects_quotes():
    assert nsis_define('C:/owned/$PLUGINSDIR') == 'C:/owned/$$PLUGINSDIR'
    for value in ['a"b', 'a\nb', 'a\rb']:
        with pytest.raises(ValueError):
            nsis_define(value)


def test_desktop_copies_complete_reviewed_package_closure_not_build_fixtures(tmp_path, monkeypatch):
    source=tmp_path / 'source'
    portable=tmp_path / 'portable'
    output=tmp_path / 'desktop'
    (source / 'scripts').mkdir(parents=True)
    name='packages/client/fixture/lib/client.js'
    path=portable / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b'original pinned browser bundle')
    row=dict(path=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (source / 'scripts/runtime-inputs.json').write_text(json.dumps(dict(files=[])),encoding='utf-8')
    (source / 'scripts/frontend-inputs.json').write_text(json.dumps(dict(files=[],client_files=[row])),encoding='utf-8')
    for base in (source,portable):
        alias=base / 'packages/bundle/creative/cordis.patch.yml'
        alias.parent.mkdir(parents=True)
        alias.write_bytes(b'[]\n')
    unused=portable / 'packages/experimental/fixture/tests/deep/fixture.txt'
    unused.parent.mkdir(parents=True)
    unused.write_bytes(b'not a runtime input')
    monkeypatch.setattr(build_desktop,'ROOT',source)
    result=build_desktop.desktop_package_inputs(portable,output)
    assert result['files'] == 2
    assert (output / name).read_bytes() == path.read_bytes()
    assert (output / 'packages/bundle/creative/cordis.patch.yml').read_bytes() == b'[]\n'
    assert not (output / unused.relative_to(portable)).exists()
    path.write_bytes(b'changed original bundle')
    with pytest.raises(ValueError,match='differs'):
        build_desktop.desktop_package_inputs(portable,tmp_path / 'rejected')


@pytest.mark.parametrize('arguments,diagnostic', [
    (['--edition','aio'], 'AIO requires --external-prereq-dir'),
    (['--architecture','x86'], 'requires an explicit qualified --portable-dir'),
])
def test_desktop_cli_rejects_missing_or_unqualified_inputs_before_writing(tmp_path, arguments, diagnostic):
    destination=tmp_path / 'output'
    result=subprocess.run([sys.executable,'-I',str(ROOT / 'scripts/build_desktop.py'),
                           '--output-dir',str(destination)] + arguments,
                           stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30,encoding='utf-8')
    assert result.returncode != 0 and diagnostic in result.stdout
    assert not destination.exists()


def invoke_cleanup(root, *arguments):
    if os.name != 'nt':
        pytest.skip('Actual Windows PowerShell installer consumer')
    return subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(ROOT / 'apps/desktop/installer/uninstall-files.ps1'),'-InstallDirectory',str(root)] + list(arguments),
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60,encoding='utf-8')


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / 'installed'
    generation = root / 'versions/0.1.5-rc.3-0123456789ab'
    generation.mkdir(parents=True)
    rows = []
    for name in ('app.exe','resources/host.py'):
        path = generation / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'owned product: ' + name.encode('ascii'))
        rows.append(hashlib.sha256(path.read_bytes()).hexdigest()+'\t'+name+'\n')
    (generation / 'dsh-owned-files.tsv').write_bytes(''.join(rows).encode('utf-8'))
    return root,generation


def test_uninstall_removes_owned_bytes_and_preserves_user_files(installed):
    root,generation = installed
    (generation / 'resources/session.jsonl').write_bytes(b'user session')
    (root / 'settings.json').write_bytes(b'user settings')
    result = invoke_cleanup(root)
    assert result.returncode == 0, result.stdout
    assert not (generation / 'app.exe').exists()
    assert not (generation / 'resources/host.py').exists()
    assert (generation / 'resources/session.jsonl').read_bytes() == b'user session'
    assert (root / 'settings.json').read_bytes() == b'user settings'


def test_uninstall_preserves_modified_product_file(installed):
    root,generation = installed
    (generation / 'app.exe').write_bytes(b'user modified executable')
    result = invoke_cleanup(root)
    assert result.returncode == 0, result.stdout
    assert (generation / 'app.exe').read_bytes() == b'user modified executable'
    assert not (generation / 'resources/host.py').exists()


def test_invalid_inventory_preserves_complete_generation(installed):
    root,generation = installed
    with (generation / 'dsh-owned-files.tsv').open('a',encoding='utf-8') as stream:
        stream.write('0'*64+'\t../settings.json\n')
    result = invoke_cleanup(root)
    assert result.returncode == 1, result.stdout
    assert (generation / 'app.exe').exists() and (generation / 'resources/host.py').exists()


def test_installer_registers_and_uninstalls_its_generated_uninstaller(installed):
    root,generation = installed
    (generation / 'uninstall.exe').write_bytes(b'generated NSIS uninstaller')
    result = invoke_cleanup(root,'-RegisterGeneration',str(generation))
    assert result.returncode == 0, result.stdout
    assert 'uninstall.exe' in (generation / 'dsh-owned-files.tsv').read_text(encoding='utf-8')
    result = invoke_cleanup(root)
    assert result.returncode == 0, result.stdout
    assert not generation.exists()


def test_extraction_rollback_only_removes_selected_owned_generation(installed):
    root, previous = installed
    failed = previous.with_name('0.1.5-rc.3-' + 'b' * 12)
    failed.mkdir()
    owned = b'partially extracted product'
    (failed / 'app.exe').write_bytes(owned)
    (failed / 'dsh-owned-files.tsv').write_text(
        hashlib.sha256(owned).hexdigest() + '\tapp.exe\n' + '0' * 64 + '\tnot-yet-extracted.dll\n', encoding='utf-8')
    (failed / 'user-notes.txt').write_bytes(b'preserve unknown data')
    before = (previous / 'app.exe').read_bytes()
    result = invoke_cleanup(root, '-RemoveGeneration', str(failed))
    assert result.returncode == 0, result.stdout
    assert (previous / 'app.exe').read_bytes() == before
    assert not (failed / 'app.exe').exists()
    assert (failed / 'user-notes.txt').read_bytes() == b'preserve unknown data'


def test_extraction_rollback_rejects_an_outside_generation(installed, tmp_path):
    root, previous = installed
    result = invoke_cleanup(root, '-RemoveGeneration', str(tmp_path / 'outside'))
    assert result.returncode == 1, result.stdout
    assert (previous / 'app.exe').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows process path check')
@pytest.mark.parametrize('inside', [True, False], ids=['owned-host', 'sibling-process'])
def test_instance_check_blocks_only_processes_under_install_root(installed, inside):
    root, generation = installed
    directory = generation if inside else root.with_name(root.name + '-other')
    directory.mkdir(exist_ok=True)
    executable = directory / 'host.exe'
    shutil.copyfile(Path(os.environ['WINDIR']) / 'System32/cmd.exe', executable)
    process = subprocess.Popen([str(executable), '/d', '/q'], stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = invoke_cleanup(root, '-CheckOnly')
        assert result.returncode == (4 if inside else 0), result.stdout
        if inside:
            assert 'PID=' + str(process.pid) in result.stdout
            assert str(executable) in result.stdout
        assert process.poll() is None  # Setup never kills an application.
        assert (generation / 'app.exe').exists()
    finally:
        process.stdin.close()
        process.wait(timeout=10)
    assert invoke_cleanup(root, '-CheckOnly').returncode == 0


@pytest.mark.parametrize('linked_root', [False, True])
def test_uninstall_rejects_junctions_without_removing_external_bytes(installed, tmp_path, linked_root):
    if os.name != 'nt':
        pytest.skip('NTFS junction consumer')
    root,generation = installed
    if linked_root:
        target = tmp_path / 'root-link'
        source = root
        selected = target
    else:
        target = generation / 'resources'
        source = tmp_path / 'external'
        target.rename(source)
        selected = root
    result = subprocess.run(['cmd.exe','/c','mklink','/J',str(target),str(source)],
                            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20)
    assert result.returncode == 0, result.stdout
    try:
        result = invoke_cleanup(selected)
        assert result.returncode == 1, result.stdout
        assert (generation / 'app.exe').exists()
        assert (generation / 'resources/host.py').exists()
    finally:
        os.rmdir(str(target))  # Remove this exact junction itself, never its target.
