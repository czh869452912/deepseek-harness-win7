import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.fs_values_cases import SOURCE_DAMAGES, VALUE_DAMAGES, damage_runtime, damage_source
from scripts.fs_values_oracle import GROUPS, ROOT, complete_digest, identity, json_values, validate_runtime
from scripts.verify_portable import fs_values_receipts


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('fs-values-pair') / 'paired.json'
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/fs_values_oracle.py'), '--output', str(output)],
        cwd=str(ROOT), capture_output=True, timeout=240)
    output.with_suffix('.log').write_bytes(process.stdout + process.stderr)
    assert process.returncode == 0, output.read_text(encoding='utf-8')
    source = json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8'))
    native = json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))
    identity(source, ROOT / 'reference')
    validate_runtime(native, ROOT, sys.executable, source, native['imports'])
    return source, native


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
