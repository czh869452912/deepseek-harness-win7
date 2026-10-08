import os
import hashlib
import importlib
import subprocess

import pytest

from scripts.import_paths import resolve_import_path


GROUPED_VALIDATORS = ('canonical', 'prepared', 'metadata', 'config', 'javascript')


def validate_grouped_imports(validator, modules, root, check_files):
    module = importlib.import_module('scripts.' + {
        'canonical': 'canonical_llm_oracle', 'prepared': 'llm_prepared_oracle',
        'metadata': 'llm_metadata_oracle', 'config': 'llm_config_oracle',
        'javascript': 'javascript_errors_oracle',
    }[validator])
    if validator == 'canonical':
        module.validate_modules(modules, root, check_files)
    else:
        module.validate_modules(modules, root, set(modules), check_files)


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


@pytest.mark.parametrize('validator', GROUPED_VALIDATORS)
@pytest.mark.parametrize('check_files', (True, False))
@pytest.mark.parametrize('state', ('missing', 'existing', 'junction', 'dangling-junction'))
def test_grouped_import_validation_retains_missing_file_and_link_refusals(tmp_path, validator, check_files, state):
    root = (tmp_path / 'runtime').resolve()
    root.mkdir()
    prefix = root / 'dsh'
    target = tmp_path / 'foreign'
    content = b'original import bytes'
    modules = {'dsh/value.py': hashlib.sha256(content).hexdigest()}
    linked = False
    try:
        if state == 'existing':
            prefix.mkdir()
            (prefix / 'value.py').write_bytes(content)
        elif state in ('junction', 'dangling-junction'):
            target.mkdir()
            if os.name == 'nt':
                completed = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(prefix), str(target)], capture_output=True)
                assert completed.returncode == 0, completed.stdout + completed.stderr
            else:
                prefix.symlink_to(target, target_is_directory=True)
            linked = True
            if state == 'dangling-junction':
                target.rmdir()
            else:
                (target / 'value.py').write_bytes(content)
        original_path = (root / 'dsh/value.py').resolve()
        try:
            escaped = original_path.relative_to(root).as_posix() != 'dsh/value.py'
        except ValueError:
            escaped = True
        if escaped:
            with pytest.raises(ValueError):
                validate_grouped_imports(validator, modules, root, check_files)
        elif check_files and not original_path.is_file():
            with pytest.raises(FileNotFoundError):
                validate_grouped_imports(validator, modules, root, check_files)
        else:
            validate_grouped_imports(validator, modules, root, check_files)
    finally:
        if linked:
            os.rmdir(str(prefix)) if os.name == 'nt' else prefix.unlink()


@pytest.mark.parametrize('validator', GROUPED_VALIDATORS)
def test_grouped_import_validation_reads_current_bytes_on_every_call(tmp_path, validator):
    root = tmp_path.resolve()
    prefix = root / 'dsh'
    prefix.mkdir()
    path = prefix / 'value.py'
    original = b'original import bytes'
    modules = {'dsh/value.py': hashlib.sha256(original).hexdigest()}
    path.write_bytes(original)
    validate_grouped_imports(validator, modules, root, True)
    path.write_bytes(b'changed import bytes')
    with pytest.raises(ValueError, match='actual imported bytes differ'):
        validate_grouped_imports(validator, modules, root, True)
