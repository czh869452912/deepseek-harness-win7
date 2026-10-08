import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.fs_values_cases import SOURCE_DAMAGES, VALUE_DAMAGES, damage_runtime, damage_source
from scripts.fs_values_oracle import GROUPS, ROOT, complete_digest, identity, json_values, validate_runtime
from scripts.verify_portable import fs_values_receipts


@pytest.fixture(scope='module')
def actual_pair_output(tmp_path_factory):
    return tmp_path_factory.mktemp('fs-values-pair') / 'paired.json'


@pytest.fixture(scope='module')
def actual_pair(actual_pair_output):
    output = actual_pair_output
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/fs_values_oracle.py'), '--output', str(output)],
        cwd=str(ROOT), capture_output=True, timeout=240)
    output.with_suffix('.log').write_bytes(process.stdout + process.stderr)
    assert process.returncode == 0, output.read_text(encoding='utf-8')
    source = json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8'))
    native = json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))
    identity(source, ROOT / 'reference')
    validate_runtime(native, ROOT, sys.executable, source, native['imports'])
    yield source, native
    # These tests are the last consumers of this pair. Retain observations and
    # prune only the isolated, byte-verified successful fixture workspace.
    from scripts.fs_fixture_workspace import cleanup
    cleanup(output)


@pytest.mark.parametrize('damage', ('foreign-owner', 'allocated', 'unmatched', 'observation',
                                   'unknown-file', 'unknown-directory', 'changed-file', 'shared-hardlink'))
def test_fixture_cleanup_refuses_unqualified_or_changed_material(actual_pair, actual_pair_output, tmp_path, damage):
    from scripts.fs_fixture_workspace import cleanup, native_path
    output = tmp_path / 'copied-pair.json'
    for suffix in ('.json', '.source.json', '.native.json', '.fixture-owner.json'):
        output.with_suffix(suffix).write_bytes(actual_pair_output.with_suffix(suffix).read_bytes())
    marker = output.with_suffix('.fixture-owner.json')
    record = json.loads(marker.read_text(encoding='utf-8'))
    record['ownerOutput'] = str(output.resolve())
    owned = Path(record['path'])
    extra, restored = None, None
    if damage == 'foreign-owner':
        record['ownerOutput'] = str(actual_pair_output)
    elif damage == 'allocated':
        record['state'] = 'allocated'
    elif damage == 'unmatched':
        output.write_text('{"status":"different"}', encoding='utf-8')
    elif damage == 'observation':
        with output.with_suffix('.native.json').open('ab') as stream:
            stream.write(b'\n')
    elif damage == 'unknown-file':
        extra = owned / 'foreign-fixture.bin'
        extra.write_bytes(b'not an owned fixture')
    elif damage == 'unknown-directory':
        extra = owned / 'foreign-empty-directory'
        extra.mkdir()
    elif damage == 'shared-hardlink':
        name = next(iter(record['files']))
        extra = tmp_path / 'outside-hardlink'
        os.link(native_path(owned / name), str(extra))
    else:
        name = next(name for name, row in record['files'].items() if not row['readonly'])
        changed = native_path(owned / name)
        with open(changed, 'rb') as stream:
            original = stream.read()
        restored = changed, original
        with open(changed, 'wb') as stream:
            stream.write(original + b'changed')
    marker.write_text(json.dumps(record), encoding='utf-8')
    try:
        with pytest.raises(ValueError):
            cleanup(output)
        assert owned.is_dir()
        assert not output.with_suffix('.fixture-cleanup.json').exists()
    finally:
        if extra is not None:
            extra.rmdir() if extra.is_dir() else extra.unlink()
        if restored is not None:
            with open(restored[0], 'wb') as stream:
                stream.write(restored[1])


def test_fixture_allocation_refuses_repository_temporary_parent(monkeypatch, tmp_path):
    from scripts import fs_fixture_workspace
    monkeypatch.setattr(fs_fixture_workspace.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(fs_fixture_workspace, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='outside'):
        fs_fixture_workspace.allocate(tmp_path / 'paired.json')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('group', GROUPS)
def test_actual_source_native_complete_fs_values(actual_pair, group):
    source, native = actual_pair
    left, right = copy.deepcopy(source['rows']), copy.deepcopy(native['rows'])
    for rows in (left, right):
        for position,row in enumerate(rows):
            if not row['name'].startswith(group + '/'):
                rows[position] = {'name': row['name']}
    assert complete_digest(left) == complete_digest(right)


@pytest.mark.parametrize('damage', VALUE_DAMAGES)
def test_fs_values_refuses_partial_changed_or_foreign_runtime(actual_pair, damage):
    source, native = actual_pair
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(damage_runtime(native, damage), ROOT, sys.executable, source, native['imports'])


@pytest.mark.parametrize('damage', SOURCE_DAMAGES)
def test_fs_values_refuses_changed_source_inputs_or_public_values(actual_pair, damage):
    source, native = actual_pair
    changed = damage_source(source, damage)
    with pytest.raises((ValueError, KeyError)):
        identity(changed, ROOT / 'reference')
        validate_runtime(native, ROOT, sys.executable, changed, native['imports'])


def test_fs_values_owned_interpreter_requires_independently_approved_imports(actual_pair, tmp_path):
    source, original = actual_pair
    native = copy.deepcopy(original)
    native['executable'] = str(ROOT / 'python.exe')
    validate_runtime(native, ROOT, ROOT / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)
    with pytest.raises(ValueError, match='closure'):
        validate_runtime(damage_runtime(native, 'module-hash'), ROOT, ROOT / 'python.exe', source,
                         original['imports'], check_files=False, owned_runtime=True)
    native['executable'] = str(tmp_path / 'python.exe')
    with pytest.raises(ValueError, match='belong'):
        validate_runtime(native, ROOT, tmp_path / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)


def test_fs_values_number_equivalence_preserves_booleans_fractions_and_surrogates():
    assert json_values({'integer': 1.0, 'fraction': 1.25, 'flag': True, 'text': '\ud83d'}) == {
        'integer': 1, 'fraction': 1.25, 'flag': True, 'text': '\ud83d'}
    assert type(json_values(True)) is bool
    with pytest.raises(ValueError, match='Nonfinite'):
        json_values(float('nan'))


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_fs_values_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both'):
        fs_values_receipts(tmp_path / 'source.json' if side == 'source' else None,
                          tmp_path / 'native.json' if side == 'native' else None, tmp_path / 'output.json')
