import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

import pytest

from scripts.build_desktop import extract_tool, nsis_define
from scripts import build_desktop

ROOT = Path(__file__).resolve().parents[1]


def test_installer_rejects_stale_electron_product_version(tmp_path):
    manifest = ROOT / 'apps/desktop/package.json'
    assert build_desktop.desktop_package_manifest(manifest) == manifest.read_bytes()
    stale = tmp_path / 'package.json'
    stale.write_text('{"version":"0.1.5-rc.3-r2"}', encoding='utf-8')
    with pytest.raises(ValueError, match='Electron package version differs'):
        build_desktop.desktop_package_manifest(stale)


@pytest.mark.parametrize('damage', [None, 'office-byte', 'extra-office', 'other-architecture', 'provider'])
def test_portable_validation_binds_offline_office_inventory_and_current_providers(tmp_path, monkeypatch, damage):
    from dsh.office import runtime_inputs
    from dsh.office.errors import OfficeKitError
    source, portable = tmp_path / 'source', tmp_path / 'portable'
    for name in ('dsh/host/desktop/process.py', 'dsh/host/desktop/health_transaction.py',
                 'apps/web/dist/index.html', 'packages/client/fixture.js'):
        for base in (source, portable):
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'current provider')
    for name in ('python.exe', 'python38.dll', 'dsh.py'):
        (portable / name).write_bytes(b'owned fixture')
    resources = {'browser/chrome.exe': b'offline executable', 'package/package.json': b'{}'}
    office = portable / 'dsh/office/bin/x64'
    manifest = dict(format='dsh-office-runtime@1', architecture='x64', executable='browser/chrome.exe',
                    package='package', resources={name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                                                  for name, data in resources.items()})
    for name, data in resources.items():
        path = office / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    raw = json.dumps(manifest).encode('utf-8')
    (office / 'runtime.json').write_bytes(raw)
    monkeypatch.setitem(runtime_inputs.MANIFESTS, 'x64', hashlib.sha256(raw).hexdigest())
    # Optional development cache is not a source provider or an approved build input.
    cache = source / 'dsh/office/bin/stale/cache.bin'
    cache.parent.mkdir(parents=True); cache.write_bytes(b'unbundled development cache')
    (portable / 'build-provenance.json').write_text(json.dumps(dict(
        python_runtime=dict(version=[3, 8, 10], bits=64), office_runtime_input=manifest)), encoding='utf-8')
    monkeypatch.setattr(build_desktop, 'ROOT', source)
    if damage == 'office-byte': (office / 'browser/chrome.exe').write_bytes(b'changed')
    if damage == 'extra-office': (office / 'undeclared.bin').write_bytes(b'not approved')
    if damage == 'other-architecture':
        other = office.parent / 'x86'
        other.mkdir(); (other / 'extra.bin').write_bytes(b'wrong architecture')
    if damage == 'provider': (portable / 'dsh/host/desktop/process.py').write_bytes(b'stale provider')
    if damage:
        with pytest.raises((ValueError, OfficeKitError)):
            build_desktop.validate_portable(portable)
    else:
        assert build_desktop.validate_portable(portable)['office_runtime_input'] == manifest


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


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows NSIS/PowerShell carrier')
def test_actual_nsis_preserves_diagnostics_and_prerequisite_restart_boundary(tmp_path):
    archive = ROOT / '.goose/tools/nsis-3.13/nsis-3.13.zip'
    if not archive.is_file():
        pytest.skip('Pinned NSIS archive is not prepared')
    identity = json.loads((ROOT / 'scripts/desktop-tool-inputs.json').read_text(encoding='utf-8'))['nsis']
    compiler = tmp_path / 'compiler'
    extract_tool(archive, identity, compiler)
    payload, prerequisites = tmp_path / 'payload', tmp_path / 'prerequisites'
    payload.mkdir()
    prerequisites.mkdir()
    (payload / 'dsh-owned-files.tsv').write_text('not extracted\n', encoding='utf-8')
    (prerequisites / 'placeholder.txt').write_text('no system updates\n', encoding='utf-8')
    observation = tmp_path / 'observed-log.txt'
    command_line = tmp_path / 'policy-command.txt'
    policy = tmp_path / 'policy.ps1'
    policy.write_text("""param([string]$Edition,[string]$Payload,[string]$LogPath)
$ErrorActionPreference='Stop'
[IO.File]::WriteAllText('__COMMAND__',[Environment]::CommandLine,[Text.Encoding]::UTF8)
[IO.File]::Copy($LogPath,'__OBSERVATION__')
Write-Host 'POLICY_REACHED'
exit 3010
""".replace('__COMMAND__', str(command_line).replace("'", "''"))
       .replace('__OBSERVATION__', str(observation).replace("'", "''")), encoding='utf-8')
    # The policy stops before any extraction, publication or system installer.
    # Lower only this fixture's UAC manifest so ordinary pytest needs no prompt.
    setup = tmp_path / 'setup.nsi'
    setup.write_text((ROOT / 'apps/desktop/installer/setup.nsi').read_text(encoding='utf-8')
                     .replace('RequestExecutionLevel admin', 'RequestExecutionLevel user'), encoding='utf-8')
    installer = tmp_path / 'restart-fixture.exe'
    definitions = dict(VERSION='0.1.5', EDITION='aio', ARCHITECTURE='x64' if sys.maxsize > 2 ** 32 else 'x86',
                       OUTPUT=installer, PAYLOAD=payload,
                       POLICY=policy, CLEANUP=ROOT / 'apps/desktop/installer/uninstall-files.ps1',
                       PUBLICATION=ROOT / 'apps/desktop/installer/publish-installation.ps1',
                       PREREQUISITES=prerequisites, MAX_INSTALL_ROOT=240)
    result = subprocess.run([str(compiler / 'nsis-3.13/makensis.exe'), '/V2'] +
                            ['/D' + name + '=' + nsis_define(value) for name, value in definitions.items()] + [str(setup)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout
    installed = tmp_path / 'installed'
    result = subprocess.run([str(installer), '/S', '/D=' + str(installed)], timeout=30)
    assert result.returncode == 3010
    diagnostic = observation.read_text(encoding='utf-8-sig')
    assert diagnostic.startswith('Setup environment:')
    assert 'Setup request: InstallDirectory=' in diagnostic
    assert diagnostic.index('Setup request:') < diagnostic.index('Instance check exit=0')
    assert '-InputFormat None' in command_line.read_text(encoding='utf-8-sig')
    assert not installed.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows NSIS upgrade')
def test_actual_nsis_upgrades_legacy_and_reuses_fixed_path(tmp_path):
    import winreg

    archive = ROOT / '.goose/tools/nsis-3.13/nsis-3.13.zip'
    if not archive.is_file():
        pytest.skip('Pinned NSIS archive is not prepared')
    identity = json.loads((ROOT / 'scripts/desktop-tool-inputs.json').read_text(encoding='utf-8'))['nsis']
    compiler = tmp_path / 'compiler'
    extract_tool(archive, identity, compiler)
    source = ROOT / 'apps/desktop/installer'
    product = 'DshSetupTest' + uuid.uuid4().hex
    menu = tmp_path / 'menu'
    fail_publication = tmp_path / 'fail-publication'
    setup = tmp_path / 'setup.nsi'
    setup.write_text((source / 'setup.nsi').read_text(encoding='utf-8')
                     .replace('DeepSeekHarnessWin7', product)
                     .replace('RequestExecutionLevel admin', 'RequestExecutionLevel user')
                     .replace(' HKLM ', ' HKCU ')
                     .replace(r'$PROGRAMFILES64\DeepSeek Harness', str(tmp_path / 'unused-default'))
                     .replace(r'$PROGRAMFILES32\DeepSeek Harness', str(tmp_path / 'unused-default'))
                     .replace(r'$SMPROGRAMS\DeepSeek Harness', str(menu)), encoding='utf-8')
    publication = tmp_path / 'publish.ps1'
    publication.write_text((source / 'publish-installation.ps1').read_text(encoding='utf-8')
                           .replace('DeepSeekHarnessWin7', product)
                           .replace('[Microsoft.Win32.Registry]::LocalMachine', '[Microsoft.Win32.Registry]::CurrentUser')
                           .replace("[IO.Path]::Combine($shell.SpecialFolders.Item('AllUsersPrograms'),'DeepSeek Harness')",
                                    "'" + str(menu).replace("'", "''") + "'")
                           .replace('[IO.File]::Copy($temporary[$index],$links[$index].Path,$true)',
                                    "if($index -eq 1 -and [IO.File]::Exists('"
                                    + str(fail_publication).replace("'", "''") + "')){throw 'test publication failure'}\n"
                                    + '    [IO.File]::Copy($temporary[$index],$links[$index].Path,$true)'), encoding='utf-8')
    policy = tmp_path / 'policy.ps1'
    policy.write_text('exit 0\n', encoding='utf-8')
    payload = tmp_path / 'payload'
    payload.mkdir()
    (payload / 'empty-packaged-directory').mkdir()
    executable = 'DeepSeek Harness.exe'
    (payload / executable).write_bytes(b'current executable')
    (payload / 'dsh-owned-files.tsv').write_text(
        hashlib.sha256(b'current executable').hexdigest() + '\t' + executable + '\n', encoding='utf-8')
    installer = tmp_path / 'setup.exe'
    definitions = dict(VERSION='0.2.2', EDITION='standard', ARCHITECTURE='x86',
                       OUTPUT=installer, PAYLOAD=payload, POLICY=policy,
                       CLEANUP=source / 'uninstall-files.ps1', PUBLICATION=publication, MAX_INSTALL_ROOT=240)
    result = subprocess.run([str(compiler / 'nsis-3.13/makensis.exe'), '/V2'] +
                            ['/D' + name + '=' + nsis_define(value) for name, value in definitions.items()] + [str(setup)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout
    root, legacy = create_installed_fixture(tmp_path / 'custom install path')
    _, legacy_rebuild = create_installed_fixture(root, '0.1.5-rc.3-fedcba987654')
    _, legacy_release = create_installed_fixture(root, '0.2.2-rc.3-r1-111122223333')
    (legacy / 'user-notes.txt').write_bytes(b'preserve legacy data')
    (legacy_release / 'resources/host.py').write_bytes(b'user-modified legacy file')
    outside, outside_release = create_installed_fixture(tmp_path / 'unregistered install path')
    registration = 'Software\\' + product
    uninstall_key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall' + '\\' + product
    view = winreg.KEY_WOW64_64KEY
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registration, access=winreg.KEY_WRITE | view) as key:
            winreg.SetValueEx(key, 'InstallLocation', 0, winreg.REG_SZ, str(root))
        # Exercise the registered custom path without using /D.
        assert subprocess.run([str(installer), '/S'], timeout=90).returncode == 0
        active = root / 'app'
        assert (active / executable).read_bytes() == b'current executable'
        assert not (legacy / 'app.exe').exists()
        assert (legacy / 'user-notes.txt').read_bytes() == b'preserve legacy data'
        assert not legacy_rebuild.exists()
        assert not (legacy_release / 'app.exe').exists()
        assert (legacy_release / 'resources/host.py').read_bytes() == b'user-modified legacy file'
        assert (outside_release / 'app.exe').read_bytes() == b'owned product: app.exe'
        assert not (outside / 'app').exists()
        (active / executable).write_bytes(b'prior active executable')
        original_inventory = (active / 'dsh-owned-files.tsv').read_text(encoding='utf-8')
        (active / 'dsh-owned-files.tsv').write_text(
            original_inventory.replace(hashlib.sha256(b'current executable').hexdigest(),
                                       hashlib.sha256(b'prior active executable').hexdigest()), encoding='utf-8')
        (active / 'user-notes.txt').write_bytes(b'preserve active data')
        links = {path.name: path.read_bytes() for path in menu.glob('*.lnk')}
        fail_publication.touch()
        assert subprocess.run([str(installer), '/S'], timeout=90).returncode == 1
        assert (active / executable).read_bytes() == b'prior active executable'
        assert (active / 'user-notes.txt').read_bytes() == b'preserve active data'
        assert {path.name: path.read_bytes() for path in menu.glob('*.lnk')} == links
        assert not (root / '.dsh-old').exists()
        assert not (root / '.dsh-new').exists()
        fail_publication.unlink()
        assert subprocess.run([str(installer), '/S'], timeout=90).returncode == 0
        assert (active / executable).read_bytes() == b'current executable'
        assert not (root / '.dsh-new').exists()
        assert not (root / '.dsh-old' / executable).exists()
        assert (root / '.dsh-old/user-notes.txt').read_bytes() == b'preserve active data'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key, access=winreg.KEY_READ | view) as key:
            assert winreg.QueryValueEx(key, 'UninstallString')[0] == '"' + str(active / 'uninstall.exe') + '"'
        assert subprocess.run([str(active / 'uninstall.exe'), '/S'], timeout=30).returncode == 0
        deadline = time.monotonic() + 30
        while (menu / 'Uninstall.lnk').exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not (menu / 'Uninstall.lnk').exists()
        assert not (active / executable).exists()
        assert (legacy / 'user-notes.txt').read_bytes() == b'preserve legacy data'
    finally:
        for key in (registration, uninstall_key):
            try:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key, access=view)
            except FileNotFoundError:
                pass


@pytest.mark.parametrize('damage', ['browser', 'native-skill'])
def test_desktop_copies_complete_reviewed_package_closure_not_build_fixtures(tmp_path, monkeypatch, damage):
    source=tmp_path / 'source'
    portable=tmp_path / 'portable'
    output=tmp_path / 'desktop'
    (source / 'scripts').mkdir(parents=True)
    name='packages/client/fixture/lib/client.js'
    path=portable / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b'original pinned browser bundle')
    row=dict(path=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    native_name='packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/references/python-api.md'
    native_path=portable / native_name
    native_path.parent.mkdir(parents=True)
    native_path.write_bytes(b'Python 3.8.10 Context bindings')
    native_row=dict(path=native_name,sha256=hashlib.sha256(native_path.read_bytes()).hexdigest(),product_owned=True)
    (source / 'scripts/runtime-inputs.json').write_text(json.dumps(dict(files=[],native_files=[native_row])),encoding='utf-8')
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
    assert result['files'] == 3
    assert (output / name).read_bytes() == path.read_bytes()
    assert (output / native_name).read_bytes() == native_path.read_bytes()
    assert (output / 'packages/bundle/creative/cordis.patch.yml').read_bytes() == b'[]\n'
    assert not (output / unused.relative_to(portable)).exists()
    (path if damage == 'browser' else native_path).write_bytes(b'changed reviewed input')
    with pytest.raises(ValueError,match='differs'):
        build_desktop.desktop_package_inputs(portable,tmp_path / 'rejected')


@pytest.mark.parametrize('damage', [None, 'missing', 'changed', 'escape'])
def test_desktop_copies_every_declared_bundle_layer(tmp_path, monkeypatch, damage):
    source, portable, output = (tmp_path / name for name in ('source', 'portable', 'desktop'))
    (source / 'scripts').mkdir(parents=True)
    layers = ['cordis.patch.yml', 'presets/standard.patch.yml',
              'presets/ptc.patch.yml', 'presets/minimal.patch.yml', 'presets/cordis.patch.yml']
    for base in (source, portable):
        package = base / 'packages/bundle/web-app'
        package.mkdir(parents=True)
        manifest = dict(name='@deepseek-ai/dsh-web-app', dsh=dict(bundle=dict(patch=layers)))
        (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
        for index, name in enumerate(layers):
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('- insert: [] # layer %s\n' % index, encoding='utf-8')
    manifest_path = source / 'packages/bundle/web-app/package.json'
    if damage == 'escape':
        manifest['dsh']['bundle']['patch'] = ['../outside.patch.yml']
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    row = dict(path='packages/bundle/web-app/package.json',
               sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    for name, files in (('runtime-inputs.json', [row]), ('frontend-inputs.json', [])):
        (source / 'scripts' / name).write_text(json.dumps(dict(files=files)), encoding='utf-8')
    last = portable / 'packages/bundle/web-app' / layers[-1]
    if damage == 'missing':
        last.unlink()
    elif damage == 'changed':
        last.write_bytes(b'changed preset')
    monkeypatch.setattr(build_desktop, 'ROOT', source)
    if damage is not None:
        with pytest.raises((ValueError, FileNotFoundError)):
            build_desktop.desktop_package_inputs(portable, output)
        return
    result = build_desktop.desktop_package_inputs(portable, output)
    assert result['files'] == 6
    for name in layers:
        path = 'packages/bundle/web-app/' + name
        assert (output / path).read_bytes() == (source / path).read_bytes()


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
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60,encoding='utf-8',errors='replace')


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
                           timeout=60, encoding='utf-8', errors='replace')


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
def test_instance_check_reports_real_path_access_denial_and_preserves_installation(tmp_path, ancestor):
    root = tmp_path / 'guard' / 'parent' / 'installed'
    root, generation = create_installed_fixture(root)
    denied = root.parent if ancestor else root
    log = tmp_path / 'denied.log'
    before = """
$denied=__DENIED__
$original=[IO.Directory]::GetAccessControl($denied)
$originalSddl=$original.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
$changed=[IO.Directory]::GetAccessControl($denied)
$guard=[IO.Path]::GetDirectoryName($denied)
$guardOriginal=[IO.Directory]::GetAccessControl($guard)
$guardOriginalSddl=$guardOriginal.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
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
  if($guardOriginal){
    $guardOriginal.SetSecurityDescriptorSddlForm($guardOriginalSddl,[Security.AccessControl.AccessControlSections]::Access)
    [IO.Directory]::SetAccessControl($guard,$guardOriginal)
  }
} finally {
  if($original){
    $original.SetSecurityDescriptorSddlForm($originalSddl,[Security.AccessControl.AccessControlSections]::Access)
    [IO.Directory]::SetAccessControl($denied,$original)
  }
}
if([IO.Directory]::GetAccessControl($guard).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) -ne $guardOriginalSddl){throw 'Guard ACL restoration failed'}
if([IO.Directory]::GetAccessControl($denied).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) -ne $originalSddl){throw 'Denied ACL restoration failed'}
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


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows PowerShell CLI')
def test_cleanup_requires_install_directory_without_interactive_prompt():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / 'apps/desktop/installer/uninstall-files.ps1'), '-CheckOnly'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, encoding='utf-8')
    assert result.returncode == 1, result.stdout
    assert 'InstallDirectory is required' in result.stdout


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows PowerShell CLI')
@pytest.mark.parametrize('missing', ['InstallDirectory', 'Version', None])
def test_publication_rejects_missing_or_invalid_inputs_before_system_changes(tmp_path, missing):
    values = dict(InstallDirectory=str(tmp_path / 'installed'), Version='0.1.5')
    arguments = []
    for name, value in values.items():
        if name != missing:
            arguments += ['-' + name, value]
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / 'apps/desktop/installer/publish-installation.ps1')] + arguments,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, encoding='utf-8')
    assert result.returncode == 1, result.stdout
    assert ('are required' if missing else 'Publication input missing') in result.stdout
    assert not (tmp_path / 'installed').exists()


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
    return create_installed_fixture(tmp_path / 'installed')


def create_installed_fixture(root, build='0.1.5-rc.3-0123456789ab'):
    generation = root / 'versions' / build
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
    root, generation = installed
    stage = root / '.dsh-new'
    generation.rename(stage)
    uninstaller = root / 'test-uninstall.exe'
    uninstaller.write_bytes(b'generated NSIS uninstaller')
    result = invoke_cleanup(root, '-StagedUninstaller', str(uninstaller))
    assert result.returncode == 0, result.stdout
    assert 'uninstall.exe' in (stage / 'dsh-owned-files.tsv').read_text(encoding='utf-8')
    active = root / 'app'
    stage.rename(active)
    result = invoke_cleanup(root)
    assert result.returncode == 0, result.stdout
    assert not active.exists()


def test_extraction_rollback_only_removes_verified_staged_files(installed):
    root, previous = installed
    failed = root / '.dsh-new'
    failed.mkdir()
    owned = b'partially extracted product'
    (failed / 'app.exe').write_bytes(owned)
    (failed / 'dsh-owned-files.tsv').write_text(
        hashlib.sha256(owned).hexdigest() + '\tapp.exe\n' + '0' * 64 + '\tnot-yet-extracted.dll\n', encoding='utf-8')
    (failed / 'user-notes.txt').write_bytes(b'preserve unknown data')
    before = (previous / 'app.exe').read_bytes()
    result = invoke_cleanup(root, '-DiscardStage')
    assert result.returncode == 0, result.stdout
    assert (previous / 'app.exe').read_bytes() == before
    assert not (failed / 'app.exe').exists()
    assert (failed / 'user-notes.txt').read_bytes() == b'preserve unknown data'


def test_prepare_install_restores_active_app_after_interrupted_directory_swap(installed):
    root, previous = installed
    backup = root / '.dsh-old'
    previous.rename(backup)
    (backup / 'DeepSeek Harness.exe').write_bytes(b'previous app')
    stage = root / '.dsh-new'
    stage.mkdir()
    (stage / 'dsh-owned-files.tsv').write_bytes(b'')
    result = invoke_cleanup(root, '-PrepareInstall')
    assert result.returncode == 0, result.stdout
    assert (root / 'app/DeepSeek Harness.exe').read_bytes() == b'previous app'
    assert not stage.exists()
    assert not backup.exists()


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
