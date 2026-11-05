import base64
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


def cleanup_probe(root, log, before='', after=''):
    if os.name != 'nt':
        pytest.skip('Actual Windows PowerShell installer consumer')
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = """
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding
$root=__ROOT__
$code=1
try {
  __BEFORE__
  & __SCRIPT__ -InstallDirectory $root -CheckOnly -LogPath __LOG__
  $code=$LASTEXITCODE
} finally { __AFTER__ }
exit $code
""".replace('__ROOT__', literal(root)).replace('__SCRIPT__', literal(
        ROOT / 'apps/desktop/installer/uninstall-files.ps1')).replace(
        '__LOG__', literal(log)).replace('__BEFORE__', before).replace('__AFTER__', after)
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                           '-EncodedCommand', encoded], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=60, encoding='utf-8')


@pytest.mark.parametrize('terminating', [False, True])
def test_instance_query_failure_preserves_error_context_and_installed_bytes(installed, tmp_path, terminating):
    root, generation = installed
    log = tmp_path / 'instance.log'
    action = "throw 'WMI unavailable'" if terminating else "Write-Error 'WMI unavailable'"
    result = cleanup_probe(root, log, before="""
function Get-WmiObject {
  [CmdletBinding()] param([Parameter(Position=0)][string]$Class)
  __ACTION__
}
""".replace('__ACTION__', action))
    assert result.returncode == 1, result.stdout
    diagnostic = log.read_text(encoding='utf-8-sig')
    assert 'Stage=process-query Path=' + str(root) in diagnostic
    for value in ('PowerShell=', 'CLR=', 'ProcessBits=', 'Administrator=', 'OS=',
                  'WMI unavailable', 'Exception=', 'ErrorId=', 'Location=', 'ScriptStack='):
        assert value in diagnostic
    assert (generation / 'app.exe').read_bytes() == b'owned product: app.exe'
    assert (generation / 'dsh-owned-files.tsv').exists()


@pytest.mark.parametrize('ancestor', [False, True], ids=['install-root', 'ancestor'])
def test_instance_check_reports_real_path_access_denial_and_preserves_installation(installed, tmp_path, ancestor):
    old_root, old_generation = installed
    root = tmp_path / 'guard' / 'parent' / 'installed'
    root.parent.mkdir(parents=True)
    old_root.rename(root)
    generation = root / old_generation.relative_to(old_root)
    denied = root.parent if ancestor else root
    log = tmp_path / 'denied.log'
    before = """
$denied=__DENIED__
$original=[IO.Directory]::GetAccessControl($denied)
$changed=[IO.Directory]::GetAccessControl($denied)
$guard=[IO.Path]::GetDirectoryName($denied)
$guardOriginal=[IO.Directory]::GetAccessControl($guard)
$guardChanged=[IO.Directory]::GetAccessControl($guard)
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$rule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ReadAttributes','Deny')
$changed.AddAccessRule($rule)
# GetFileAttributes can obtain attributes through a parent's directory listing.
# Deny that alternative on a second, independently owned fixture directory.
$guardRule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'ListDirectory','Deny')
$guardChanged.AddAccessRule($guardRule)
[IO.Directory]::SetAccessControl($denied,$changed)
[IO.Directory]::SetAccessControl($guard,$guardChanged)
""".replace('__DENIED__', "'" + str(denied).replace("'", "''") + "'")
    result = cleanup_probe(root, log, before=before,
                           after="""
try {
  if($guardOriginal){[IO.Directory]::SetAccessControl($guard,$guardOriginal)}
} finally {
  if($original){[IO.Directory]::SetAccessControl($denied,$original)}
}
""")
    assert result.returncode == 1, result.stdout
    diagnostic = log.read_text(encoding='utf-8-sig')
    stage = 'path-attributes' if ancestor else 'install-directory-attributes'
    assert 'Stage=' + stage + ' Path=' + str(denied) in diagnostic
    assert 'System.UnauthorizedAccessException' in diagnostic
    assert 'Location=' in diagnostic and 'uninstall-files.ps1' in diagnostic
    assert (generation / 'app.exe').read_bytes() == b'owned product: app.exe'
    assert (generation / 'dsh-owned-files.tsv').exists()


def test_instance_check_missing_directory_is_distinct_from_access_denial(tmp_path):
    log = tmp_path / 'missing.log'
    result = cleanup_probe(tmp_path / 'not-installed', log)
    assert result.returncode == 0, result.stdout
    assert 'does not exist' in log.read_text(encoding='utf-8-sig')


def test_instance_check_rejects_file_as_installation_directory(tmp_path):
    root = tmp_path / 'file'
    root.write_bytes(b'preserve')
    log = tmp_path / 'file.log'
    result = cleanup_probe(root, log)
    assert result.returncode == 1, result.stdout
    assert 'not a directory' in log.read_text(encoding='utf-8-sig')
    assert root.read_bytes() == b'preserve'


def test_instance_check_writes_untruncated_utf8_diagnostics(installed, tmp_path):
    root, _ = installed
    log = tmp_path / 'full.log'
    # Longer than the NSIS default string/ExecToStack output buffer.
    message = '访问被拒绝' + 'x' * 2000 + 'END-OF-ERROR'
    result = cleanup_probe(root, log, before="""
function Get-WmiObject {
  [CmdletBinding()] param([Parameter(Position=0)][string]$Class)
  throw '__MESSAGE__'
}
""".replace('__MESSAGE__', message))
    assert result.returncode == 1, result.stdout
    assert message in log.read_text(encoding='utf-8-sig')


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


@pytest.mark.skipif(os.name != 'nt', reason='NTFS junction consumer')
def test_instance_check_rejects_linked_ancestor_and_logs_its_path(installed, tmp_path):
    root, generation = installed
    alias = tmp_path / 'parent-link'
    result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(alias), str(root.parent)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    assert result.returncode == 0, result.stdout
    log = tmp_path / 'linked.log'
    try:
        result = cleanup_probe(alias / 'installed', log)
        assert result.returncode == 1, result.stdout
        diagnostic = log.read_text(encoding='utf-8-sig')
        assert 'Stage=path-attributes Path=' + str(alias) in diagnostic
        assert 'linked path' in diagnostic
        assert (generation / 'app.exe').read_bytes() == b'owned product: app.exe'
    finally:
        os.rmdir(str(alias))
