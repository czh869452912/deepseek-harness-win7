import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.javascript_errors_cases import VALUE_DAMAGES, SOURCE_DAMAGES, damage_runtime, damage_source
from scripts.javascript_errors_oracle import NAMES, identity, normalize_platform_observations, validate_runtime


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('javascript-errors-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_errors_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=360)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode('utf-8', errors='replace')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_original_and_native_javascript_error_boundaries_match(actual_pair, name):
    source, native = actual_pair
    source_rows = normalize_platform_observations(source['rows'], 'source')
    native_rows = normalize_platform_observations(native['rows'], 'native')
    assert next(row for row in native_rows if row['name'] == name) == next(
        row for row in source_rows if row['name'] == name)
    validate_runtime(native, ROOT, identity(source), native['modules'], native['assets'])


@pytest.mark.parametrize('damage', VALUE_DAMAGES)
def test_javascript_error_receipt_requires_complete_values_and_owned_runtime(actual_pair, tmp_path, damage):
    source, native = actual_pair
    altered = damage_runtime(native, damage, tmp_path)
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(altered, ROOT, identity(source), native['modules'], native['assets'])


@pytest.mark.parametrize('damage', SOURCE_DAMAGES)
def test_javascript_error_source_requires_pinned_complete_inputs(actual_pair, damage):
    altered = damage_source(actual_pair[0], damage)
    with pytest.raises((ValueError, KeyError)):
        identity(altered)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_javascript_errors_refuses_partial_receipts(tmp_path, side):
    from scripts.verify_portable import errors_receipts
    receipt = tmp_path / 'missing.json'
    with pytest.raises(RuntimeError, match='Both JavaScript errors'):
        errors_receipts(receipt if side == 'source' else None,
            receipt if side == 'native' else None, tmp_path / 'output.json')


def test_extracted_javascript_errors_requires_independently_approved_assets(actual_pair):
    source, native = actual_pair
    native = copy.deepcopy(native)
    native['executable'] = str(ROOT / 'python.exe')
    for child in native['groups'].values():
        child['executable'] = native['executable']
    expected = identity(source)
    validate_runtime(native, ROOT, expected, native['modules'], native['assets'], check_files=False)
    with pytest.raises(ValueError, match='Approved JavaScript private assets'):
        validate_runtime(native, ROOT, expected, native['modules'], check_files=False)
