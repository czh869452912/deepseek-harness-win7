"""Release preflight protects a valid distribution from incomplete input checkouts."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import json
import os
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('portable_preflight', ROOT/'scripts/build_portable.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


@pytest.fixture(autouse=True)
def prune_finished_preflight_case(request):
    if request.node.originalname != 'test_invalid_input_fails_before_release_replacement':
        yield
        return
    from scripts.process_artifact_retention import preflight_test_inputs, prune_finished_preflight_folder
    folder = request.getfixturevalue('tmp_path')
    workspace = request.config._tmp_path_factory._basetemp
    output_root = ROOT / '.goose/out'
    frozen = preflight_test_inputs(output_root, workspace, ROOT, os.environ.get('DSH_RELEASE_PYTEST_OUTPUT'))
    yield
    if frozen is not None:
        prune_finished_preflight_folder(output_root, workspace, folder, ROOT, frozen)


def test_real_frontend_and_runtime_lock_are_resolvable():
    frontend, dependencies = BUILD.checked_inputs(ROOT, ROOT/'.venv/Lib/site-packages')
    assert frontend['kind'] == 'versioned-prebuilt-input'
    assert {d.metadata['Name'].lower() for d in dependencies} == {
        'pyyaml','requests','certifi','charset-normalizer','idna','urllib3','pillow','wsproto','h11','backports.zoneinfo','tzdata','pywinpty', 'opentelemetry-api', 'opentelemetry-sdk',
        'opentelemetry-semantic-conventions', 'opentelemetry-exporter-otlp-proto-common',
        'opentelemetry-exporter-otlp-proto-http', 'opentelemetry-proto', 'protobuf',
        'googleapis-common-protos', 'deprecated', 'wrapt', 'importlib_metadata', 'zipp', 'typing_extensions'}


def test_portable_dependency_copy_preserves_winpty_agent_and_native_dll(tmp_path):
    _, dependencies = BUILD.checked_inputs(ROOT, ROOT/'.venv/Lib/site-packages')
    winpty = next(dist for dist in dependencies if dist.metadata['Name'].lower() == 'pywinpty')
    destination = tmp_path / 'lib'
    BUILD.bundle_dependencies([winpty], destination)
    assert (destination / 'winpty/winpty.dll').is_file()
    assert (destination / 'winpty/winpty-agent.exe').is_file()


def test_portable_dependency_copy_preserves_native_image_codecs(tmp_path):
    _, dependencies = BUILD.checked_inputs(ROOT, ROOT/'.venv/Lib/site-packages')
    pillow = next(dist for dist in dependencies if dist.metadata['Name'].lower() == 'pillow')
    destination = tmp_path / 'lib'
    BUILD.bundle_dependencies([pillow], destination)
    native = [path for path in pillow.files if path.suffix.lower() in ('.pyd', '.dll')]
    assert native
    assert all((destination / path).is_file() for path in native)


@pytest.mark.parametrize('damage', ['missing-frontend','extra-frontend','wrong-target','missing-runtime', 'missing-icu', 'changed-icu-license', 'missing-case-fold', 'changed-case-fold', 'missing-zstd', 'changed-zstd-license', 'changed-zstd-dictionary', 'missing-sql', 'changed-sql', 'changed-sql-manifest', 'missing-client', 'changed-client', 'extra-client', 'wrong-build-profile'])
def test_invalid_input_fails_before_release_replacement(tmp_path, monkeypatch, damage):
    import shutil
    root = tmp_path/'checkout'
    shutil.copytree(ROOT/'dsh/session/bin/icu', root/'dsh/session/bin/icu')
    shutil.copytree(ROOT/'dsh/session/bin/zstd', root/'dsh/session/bin/zstd')
    shutil.copytree(ROOT/'dsh/session/bin/unicode', root/'dsh/session/bin/unicode')
    shutil.copytree(ROOT/'dsh/session/resources/sql', root/'dsh/session/resources/sql')
    shutil.copytree(ROOT/'apps/web/dist', root/'apps/web/dist')
    (root/'scripts').mkdir()
    shutil.copyfile(ROOT/'scripts/frontend-inputs.json',root/'scripts/frontend-inputs.json')
    frontend = json.loads((root/'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
    for row in frontend['client_files']:
        destination = root/row['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/row['path'], destination)
    (root/'migration').mkdir()
    shutil.copyfile(ROOT/'migration/baseline.json',root/'migration/baseline.json')
    (root/'reference/apps/cli').mkdir(parents=True)
    (root/'reference/apps/cli/package.json').write_text('{}',encoding='utf-8')
    shutil.copyfile(ROOT/'requirements-runtime.lock',root/'requirements-runtime.lock')
    BUILD.checked_inputs(root, ROOT/'.venv/Lib/site-packages')
    if damage=='missing-frontend': (root/'apps/web/dist/index.html').unlink()
    if damage=='extra-frontend': (root/'apps/web/dist/stale.js').write_text('stale',encoding='utf-8')
    if damage=='wrong-target': (root/'migration/baseline.json').write_text('{"target_upstream":"wrong"}',encoding='utf-8')
    if damage=='missing-icu': (root/'dsh/session/bin/icu/dsh_icuin78.dll').unlink()
    if damage=='changed-icu-license': (root/'dsh/session/bin/icu/ICU-LICENSE').write_text('changed',encoding='utf-8')
    if damage=='missing-case-fold': (root/'dsh/session/bin/unicode/CaseFolding.txt').unlink()
    if damage=='changed-case-fold': (root/'dsh/session/bin/unicode/CaseFolding.txt').write_text('changed',encoding='utf-8')
    if damage=='missing-zstd': (root/'dsh/session/bin/zstd/dsh_zstd.dll').unlink()
    if damage=='changed-zstd-license': (root/'dsh/session/bin/zstd/ZSTD-LICENSE').write_text('changed',encoding='utf-8')
    if damage=='changed-zstd-dictionary': (root/'dsh/session/bin/zstd/zstd-dictionary.bin').write_bytes(b'changed')
    if damage=='missing-sql': (root/'dsh/session/resources/sql/schema.sql').unlink()
    if damage=='changed-sql': (root/'dsh/session/resources/sql/schema.sql').write_text('changed',encoding='utf-8')
    if damage=='changed-sql-manifest': (root/'dsh/session/resources/sql/manifest.json').write_text('{}',encoding='utf-8')
    if damage=='missing-client': (root/frontend['client_files'][0]['path']).unlink()
    if damage=='changed-client': (root/frontend['client_files'][0]['path']).write_text('changed',encoding='utf-8')
    if damage=='extra-client': (root/'packages/client/unknown/lib').mkdir(parents=True); (root/'packages/client/unknown/lib/client.js').write_text('changed',encoding='utf-8')
    if damage=='wrong-build-profile':
        frontend['build_record']['environment']['DSH_CLIENT_BUILD_PROFILE'] = 'local'
        (root/'scripts/frontend-inputs.json').write_text(json.dumps(frontend),encoding='utf-8')
    dist=root/'dist/dsh-win7-portable';dist.mkdir(parents=True)
    (dist/'sentinel').write_text('last successful release',encoding='utf-8')
    monkeypatch.setattr(BUILD,'ROOT_DIR',str(root));monkeypatch.setattr(BUILD,'DIST_DIR',str(dist))
    # No rg binary is needed: use a pinned metadata fixture for the preflight.
    fake=root/'rg/bin/rg.exe';fake.parent.mkdir(parents=True);fake.write_bytes(b'rg')
    (fake.parent.parent/'package.json').write_text('{"name":"@vscode/ripgrep-win32-x64","version":"1.18.0"}',encoding='utf-8')
    site=tmp_path/'absent' if damage=='missing-runtime' else ROOT/'.venv/Lib/site-packages'
    with pytest.raises((ValueError,FileNotFoundError,RuntimeError)):
        BUILD.build_portable(runtime_dir=sys.base_prefix,ripgrep_source=str(fake),site_packages=site)
    assert (dist/'sentinel').read_text(encoding='utf-8')=='last successful release'


def test_release_cli_exposes_explicit_dependency_directory():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/build_portable.py'),'--help'],capture_output=True,text=True)
    assert result.returncode==0 and '--site-packages' in result.stdout and '--output-dir' in result.stdout


def test_real_runtime_identity_and_hashes_are_observed():
    identity = BUILD.inspect_runtime(sys.base_prefix)
    assert identity['version'] == [3, 8, 10] and identity['platform'] == 'win32' and identity['bits'] == 64
    assert set(identity['files']) == {'python.exe', 'python38.dll'}
    assert all(len(digest) == 64 for digest in identity['files'].values())


@pytest.mark.parametrize('observed', [dict(version=[3, 8, 0], platform='win32', bits=64),
                                    dict(version=[3, 8, 10], platform='win32', bits=32),
                                    dict(version=[3, 8, 10], platform='linux', bits=64)])
def test_runtime_filename_cannot_substitute_for_actual_identity(monkeypatch, observed):
    monkeypatch.setattr(BUILD.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=json.dumps(observed)))
    with pytest.raises(ValueError, match='actual Windows x64 Python 3.8.10'):
        BUILD.inspect_runtime('unused')


@pytest.mark.parametrize('failure', ['assembly', 'zip', 'directory-backup', 'zip-backup', 'directory-publish', 'zip-publish'])
def test_candidate_failure_retains_both_previous_artifacts(tmp_path, monkeypatch, failure):
    parent = tmp_path / 'output'
    dist = parent / 'dsh-win7-portable'
    dist.mkdir(parents=True)
    (dist / 'previous').write_bytes(b'old directory')
    archive = parent / 'dsh-win7-portable-v0.1.0.zip'
    archive.write_bytes(b'old zip')
    def assemble(directory, output, *args):
        Path(directory).mkdir()
        (Path(directory) / 'candidate').write_bytes(b'new directory')
        if failure == 'assembly':
            raise OSError('fixture assembly failure')
        Path(output).write_bytes(b'new zip')
        if failure == 'zip':
            raise OSError('fixture ZIP failure')
    monkeypatch.setattr(BUILD, 'assemble_portable', assemble)
    real_replace = BUILD.os.replace
    failed = [False]
    def replace(source, destination):
        source, destination = Path(source), Path(destination)
        selected = ((failure == 'directory-backup' and source == dist) or
                    (failure == 'zip-backup' and source == archive) or
                    (failure == 'directory-publish' and destination == dist and source.name == dist.name) or
                    (failure == 'zip-publish' and destination == archive and source.name == archive.name))
        if selected and not failed[0]:
            failed[0] = True
            raise OSError('fixture publication failure')
        return real_replace(source, destination)
    monkeypatch.setattr(BUILD.os, 'replace', replace)
    with pytest.raises(OSError, match='fixture'):
        BUILD.build_portable(output_dir=str(parent))
    assert (dist / 'previous').read_bytes() == b'old directory'
    assert archive.read_bytes() == b'old zip'
    assert not list(parent.glob('.dsh-portable-candidate-*'))


def test_failed_publication_rollback_keeps_recoverable_backup(tmp_path, monkeypatch):
    parent = tmp_path / 'output'
    dist = parent / 'dsh-win7-portable'
    dist.mkdir(parents=True)
    (dist / 'previous').write_bytes(b'old directory')
    archive = parent / 'dsh-win7-portable-v0.1.0.zip'
    archive.write_bytes(b'old zip')
    def assemble(directory, output, *args):
        Path(directory).mkdir()
        Path(output).write_bytes(b'new zip')
    monkeypatch.setattr(BUILD, 'assemble_portable', assemble)
    real_replace = BUILD.os.replace
    def replace(source, destination):
        if Path(destination) == archive or Path(source).name.startswith('previous-'):
            raise OSError('fixture storage failure')
        return real_replace(source, destination)
    monkeypatch.setattr(BUILD.os, 'replace', replace)
    with pytest.raises(OSError, match='fixture storage failure'):
        BUILD.build_portable(output_dir=str(parent))
    retained = list(parent.glob('.dsh-portable-candidate-*'))
    assert len(retained) == 1
    assert (retained[0] / 'previous-0/previous').read_bytes() == b'old directory'
    assert (retained[0] / 'previous-1').read_bytes() == b'old zip'


def test_isolated_candidate_publication_preserves_default_output(tmp_path, monkeypatch):
    default = tmp_path / 'default/dsh-win7-portable'
    default.mkdir(parents=True)
    (default / 'previous').write_bytes(b'default stays')
    monkeypatch.setattr(BUILD, 'DIST_DIR', str(default))
    def assemble(directory, output, *args):
        Path(directory).mkdir()
        (Path(directory) / 'candidate').write_bytes(b'new directory')
        Path(output).write_bytes(b'new zip')
    monkeypatch.setattr(BUILD, 'assemble_portable', assemble)
    dist, archive = BUILD.build_portable(output_dir=str(tmp_path / 'isolated'))
    assert (default / 'previous').read_bytes() == b'default stays'
    assert (Path(dist) / 'candidate').read_bytes() == b'new directory'
    assert Path(archive).read_bytes() == b'new zip'
    assert not list(Path(dist).parent.glob('.dsh-portable-candidate-*'))


def test_candidate_outputs_cannot_replace_build_inputs(tmp_path):
    with pytest.raises(ValueError, match='overlaps a build input'):
        BUILD.build_portable(output_dir=str(ROOT / 'dsh'))
