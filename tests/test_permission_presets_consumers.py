import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.canonical_llm_values import observation_digest as value_digest
from scripts.permission_presets_cases import SOURCE_DAMAGES, VALUE_DAMAGES, damage_runtime, damage_source
from scripts.permission_presets_oracle import identity, validate_runtime
from scripts.permission_presets_values import ALL_NAMES, complete_digest, schema_graph
from scripts.verify_portable import permission_presets_receipts


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('permission-presets-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/permission_presets_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=240)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode('utf-8', errors='replace')
    source = json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8'))
    native = json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))
    identity(source, ROOT / 'reference')
    validate_runtime(native, ROOT, sys.executable, source, native['modules'])
    return source, native


def selected_row_digest(report, name, side):
    group, case = name.split('/', 1)
    selected = copy.deepcopy(next(row for row in report['groups'][group]['rows'] if row['name'] == case))
    if group == 'lifecycle' and case in ('settings-labels', 'live-default'):
        for descriptor in selected.get('descriptors', selected.get('value')):
            descriptor['schema'] = schema_graph(descriptor['schema'])
    return value_digest([dict(name=name, group='retry', rows=[selected])], side=side)


@pytest.mark.parametrize('name', ALL_NAMES)
def test_actual_source_native_permission_presets_complete_observations(actual_pair, name):
    source, native = actual_pair
    assert selected_row_digest(source, name, 'source') == selected_row_digest(native, name, 'native')


@pytest.mark.parametrize('damage', VALUE_DAMAGES)
def test_permission_presets_requires_complete_observations_and_owned_runtime(actual_pair, tmp_path, damage):
    source, native = actual_pair
    altered = damage_runtime(native, damage, tmp_path)
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(altered, ROOT, sys.executable, source, native['modules'])


@pytest.mark.parametrize('damage', SOURCE_DAMAGES)
def test_permission_presets_source_requires_pinned_guarded_inputs(actual_pair, damage):
    altered = damage_source(actual_pair[0], damage)
    with pytest.raises((ValueError, KeyError)):
        identity(altered, ROOT / 'reference')


def test_permission_presets_extracted_requires_independently_approved_imports(actual_pair):
    source, original = actual_pair
    native = copy.deepcopy(original)
    native['executable'] = str(ROOT / 'python.exe')
    for child in native['groups'].values():
        child['executable'] = native['executable']
    validate_runtime(native, ROOT, ROOT / 'python.exe', source, original['modules'], check_files=False)
    altered = copy.deepcopy(native)
    provider = 'dsh/interaction/permission_presets.py'
    altered['modules'][provider] = '0' * 64
    for child in altered['groups'].values():
        if provider in child['modules']:
            child['modules'][provider] = '0' * 64
    with pytest.raises(ValueError, match='imported closure'):
        validate_runtime(altered, ROOT, ROOT / 'python.exe', source, original['modules'], check_files=False)


@pytest.mark.parametrize('group', ('lifecycle', 'domain'))
def test_permission_presets_complete_digest_refuses_missing_group(actual_pair, group):
    altered = copy.deepcopy(actual_pair[0])
    del altered['groups'][group]
    with pytest.raises(ValueError, match='complete child groups'):
        complete_digest(altered, 'source')


def test_permission_presets_selected_interpreter_must_belong_to_root(actual_pair, tmp_path):
    source, original = actual_pair
    native = copy.deepcopy(original)
    executable = tmp_path / 'python.exe'
    native['executable'] = str(executable)
    for child in native['groups'].values():
        child['executable'] = str(executable)
    with pytest.raises(ValueError):
        validate_runtime(native, ROOT, executable, source, original['modules'], check_files=False, owned_runtime=True)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_permission_presets_refuses_partial_receipts(tmp_path, side):
    path = tmp_path / 'unreadable.json'
    source, native = (path, None) if side == 'source' else (None, path)
    with pytest.raises(RuntimeError, match='Both permission presets'):
        permission_presets_receipts(source, native, tmp_path / 'output.json')
