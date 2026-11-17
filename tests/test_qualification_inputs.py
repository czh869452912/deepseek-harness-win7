"""A frozen gate must notice installed code and runtime changes, not just locks."""
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace

import pytest

from scripts import qualification_inputs as inputs


@pytest.mark.parametrize('change', ['bytes', 'added', 'removed'])
def test_installed_dependency_changes_invalidate_freeze(tmp_path, change):
    package = tmp_path / 'node_modules/package'
    package.mkdir(parents=True)
    module = package / 'index.js'; module.write_bytes(b'original')
    before = inputs.tree_identity([package.parent], [tmp_path])
    if change == 'bytes': module.write_bytes(b'modified')
    if change == 'added': (package / 'extra.js').write_bytes(b'extra')
    if change == 'removed': module.unlink()
    assert inputs.tree_identity([package.parent], [tmp_path]) != before


def directory_link(path, target):
    if os.name == 'nt':
        completed = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(path), str(target)],
                                   capture_output=True, timeout=10)
        assert completed.returncode == 0, completed.stderr
    else:
        path.symlink_to(target, target_is_directory=True)


def test_directory_cycle_preserves_links_without_rewalking_target(tmp_path):
    package = tmp_path / 'package'; package.mkdir()
    (package / 'index.js').write_bytes(b'module')
    link = package / 'parent'; directory_link(link, tmp_path)
    try:
        value = inputs.tree_identity([package], [tmp_path])
        assert value['files'] == {str(package / 'index.js'): inputs.digest(package / 'index.js')}
        assert value['links'] == {str(link): str(tmp_path)}
    finally:
        if os.name == 'nt': os.rmdir(str(link))
        else: link.unlink()


def test_link_outside_approved_inputs_is_rejected(tmp_path):
    owned = tmp_path / 'owned'; owned.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    link = owned / 'dependency'; directory_link(link, outside)
    try:
        with pytest.raises(ValueError, match='escaped approved'):
            inputs.tree_identity([owned], [owned])
    finally:
        if os.name == 'nt': os.rmdir(str(link))
        else: link.unlink()


def test_unavailable_dependency_target_is_bound_and_cannot_appear_during_gate(tmp_path):
    target = tmp_path / 'optional'; target.mkdir()
    link = tmp_path / 'dependency'; directory_link(link, target)
    target.rmdir()
    try:
        before = inputs.tree_identity([tmp_path], [tmp_path])
        assert before['missing_links'] == {str(link): str(target)}
        target.mkdir(); (target / 'index.js').write_bytes(b'newly available')
        assert inputs.tree_identity([tmp_path], [tmp_path]) != before
    finally:
        if os.name == 'nt': os.rmdir(str(link))
        else: link.unlink()


def test_only_documented_volatile_inputs_are_excluded(tmp_path):
    (tmp_path / 'index.js').write_bytes(b'code')
    before = inputs.tree_identity([tmp_path], [tmp_path])
    for name in inputs.VOLATILE_DIRECTORIES:
        folder = tmp_path / name; folder.mkdir(); (folder / 'cache').write_bytes(b'volatile')
    (tmp_path / 'module.pyc').write_bytes(b'cache')
    assert inputs.tree_identity([tmp_path], [tmp_path]) == before
    generated = tmp_path / 'lib'; generated.mkdir(); (generated / 'index.js').write_bytes(b'built code')
    assert inputs.tree_identity([tmp_path], [tmp_path]) != before


def python_fixture(tmp_path, monkeypatch):
    from scripts import build_portable as builder
    runtime = tmp_path / 'runtime'; runtime.mkdir()
    site = tmp_path / 'site'; site.mkdir()
    for name in ['python.exe', 'python38.dll', 'Lib/os.py', 'DLLs/extension.pyd']:
        path = runtime / name; path.parent.mkdir(exist_ok=True); path.write_bytes(name.encode('ascii'))
    package = site / 'package.py'; package.write_bytes(b'locked dependency')
    distribution = SimpleNamespace(metadata={'Name': 'package'}, version='1', files=[Path('package.py')],
                                   locate_file=lambda name: site / name)
    monkeypatch.setattr(builder, 'inspect_runtime', lambda directory, architecture: dict(bits=32 if architecture == 'x86' else 64))
    monkeypatch.setattr(builder, 'checked_inputs', lambda root, directory, architecture: ({}, [distribution]))
    return runtime, site


@pytest.mark.parametrize('name', ['Lib/os.py', 'DLLs/extension.pyd', 'python38.dll', '../site/package.py'])
def test_python_freeze_binds_actual_copied_runtime_and_locked_package_bytes(tmp_path, monkeypatch, name):
    runtime, site = python_fixture(tmp_path, monkeypatch)
    before = inputs.python_identity(tmp_path, runtime, site, 'x86')
    assert before['observed']['bits'] == 32
    (runtime / name).write_bytes(b'changed')
    assert inputs.python_identity(tmp_path, runtime, site, 'x86') != before


def test_python_lock_cannot_copy_an_unapproved_external_file(tmp_path, monkeypatch):
    from scripts import build_portable as builder
    runtime, site = python_fixture(tmp_path, monkeypatch)
    outside = tmp_path / 'foreign.py'; outside.write_bytes(b'foreign')
    distribution = SimpleNamespace(metadata={'Name': 'package'}, version='1', files=[Path('package.py')],
                                   locate_file=lambda name: outside)
    monkeypatch.setattr(builder, 'checked_inputs', lambda *args: ({}, [distribution]))
    with pytest.raises(ValueError, match='escaped approved'):
        inputs.python_identity(tmp_path, runtime, site, 'x64')
