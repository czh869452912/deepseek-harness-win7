"""Release preflight protects a valid distribution from incomplete input checkouts."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('portable_preflight', ROOT/'scripts/build_portable.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def test_real_frontend_and_runtime_lock_are_resolvable():
    frontend, dependencies = BUILD.checked_inputs(ROOT, ROOT/'.venv/Lib/site-packages')
    assert frontend['kind'] == 'versioned-prebuilt-input'
    assert {d.metadata['Name'].lower() for d in dependencies} == {
        'pyyaml','requests','certifi','charset-normalizer','idna','urllib3','pillow','wsproto','h11','backports.zoneinfo','tzdata','pywinpty'}


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


@pytest.mark.parametrize('damage', ['missing-frontend','extra-frontend','wrong-target','missing-runtime'])
def test_invalid_input_fails_before_release_replacement(tmp_path, monkeypatch, damage):
    import shutil
    root = tmp_path/'checkout'
    shutil.copytree(ROOT/'apps/web/dist', root/'apps/web/dist')
    (root/'scripts').mkdir()
    shutil.copyfile(ROOT/'scripts/frontend-inputs.json',root/'scripts/frontend-inputs.json')
    (root/'migration').mkdir()
    shutil.copyfile(ROOT/'migration/baseline.json',root/'migration/baseline.json')
    (root/'reference/apps/cli').mkdir(parents=True)
    (root/'reference/apps/cli/package.json').write_text('{}',encoding='utf-8')
    shutil.copyfile(ROOT/'requirements-runtime.lock',root/'requirements-runtime.lock')
    if damage=='missing-frontend': (root/'apps/web/dist/index.html').unlink()
    if damage=='extra-frontend': (root/'apps/web/dist/stale.js').write_text('stale',encoding='utf-8')
    if damage=='wrong-target': (root/'migration/baseline.json').write_text('{"target_upstream":"wrong"}',encoding='utf-8')
    dist=root/'dist/dsh-win7-portable';dist.mkdir(parents=True)
    (dist/'sentinel').write_text('last successful release',encoding='utf-8')
    monkeypatch.setattr(BUILD,'ROOT_DIR',str(root));monkeypatch.setattr(BUILD,'DIST_DIR',str(dist))
    # No rg binary is needed: use a pinned metadata fixture for the preflight.
    fake=root/'rg/bin/rg.exe';fake.parent.mkdir(parents=True);fake.write_bytes(b'rg')
    (fake.parent.parent/'package.json').write_text('{"name":"@vscode/ripgrep-win32-x64","version":"1.18.0"}',encoding='utf-8')
    site=tmp_path/'absent' if damage=='missing-runtime' else ROOT/'.venv/Lib/site-packages'
    with pytest.raises((ValueError,FileNotFoundError)):
        BUILD.build_portable(runtime_dir=sys.base_prefix,ripgrep_source=str(fake),site_packages=site)
    assert (dist/'sentinel').read_text(encoding='utf-8')=='last successful release'


def test_release_cli_exposes_explicit_dependency_directory():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/build_portable.py'),'--help'],capture_output=True,text=True)
    assert result.returncode==0 and '--site-packages' in result.stdout
