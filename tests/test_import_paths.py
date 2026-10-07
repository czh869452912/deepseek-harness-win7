import os
import subprocess

import pytest

from scripts.import_paths import resolve_import_path


@pytest.mark.parametrize('check_files', (True, False))
@pytest.mark.parametrize('state', ('missing', 'existing', 'junction', 'dangling-junction'))
def test_import_paths_preserves_original_physical_resolution(tmp_path, check_files, state):
    root = tmp_path.resolve()
    selected = root / 'dsh'
    target = root / 'target'
    linked = False
    try:
        if state == 'existing':
            selected.mkdir()
        elif state in ('junction', 'dangling-junction'):
            target.mkdir()
            if os.name == 'nt':
                completed = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(selected), str(target)], capture_output=True)
                assert completed.returncode == 0, completed.stdout + completed.stderr
            else:
                selected.symlink_to(target, target_is_directory=True)
            linked = True
            if state == 'dangling-junction':
                target.rmdir()
        missing_prefixes = None if check_files else {}
        for name in ('dsh/value.py', 'dsh/core/missing.py', 'dsh/../foreign.py', 'dsh//value.py'):
            observed = resolve_import_path(root, name, missing_prefixes)
            assert observed == (root / name).resolve()
            if state == 'junction' and name == 'dsh/value.py':
                assert observed.relative_to(root).as_posix() != name
    finally:
        if linked:
            os.rmdir(str(selected)) if os.name == 'nt' else selected.unlink()


@pytest.mark.parametrize('check_files', (True, False))
def test_import_paths_live_prefix_never_uses_missing_tree_shortcut(tmp_path, check_files):
    root = tmp_path.resolve()
    prefix = root / 'dsh'
    prefix.mkdir()
    missing_prefixes = None if check_files else {}
    path = prefix / 'value.py'
    path.write_text('original', encoding='utf-8')
    assert resolve_import_path(root, 'dsh/value.py', missing_prefixes).read_text(encoding='utf-8') == 'original'
    path.write_text('modified', encoding='utf-8')
    assert resolve_import_path(root, 'dsh/value.py', missing_prefixes).read_text(encoding='utf-8') == 'modified'
    if not check_files:
        assert missing_prefixes == {'dsh': False}
