import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import query_unicode_oracle


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    output = tmp_path_factory.mktemp('query-unicode-paired') / 'result.json'
    result = subprocess.run([sys.executable, str(query_unicode_oracle.ROOT / 'scripts/query_unicode_oracle.py'),
                             '--output', str(output)], capture_output=True, timeout=120, env=os.environ.copy())
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    report = json.loads(output.read_text(encoding='utf-8'))
    native = json.loads(output.with_name('result.native.json').read_text(encoding='utf-8'))
    return report, native


def test_actual_original_native_unicode_and_cursor_observations(paired):
    report, native = paired
    assert (report['status'], report['comparisons'], report['fingerprints'], report['cursors'], report['cases']) == ('passed', 1849, 180, 5, 2034)
    query_unicode_oracle.validate_runtime(native, query_unicode_oracle.ROOT)


@pytest.mark.parametrize('field,value', [('root', ''), ('moduleFile', 'foreign.py'), ('python', '3.9.0'),
                                       ('runtime', None), ('observations', None)])
def test_foreign_or_missing_runtime_receipt_is_refused(paired, field, value):
    damaged = copy.deepcopy(paired[1])
    damaged[field] = value
    with pytest.raises(ValueError):
        query_unicode_oracle.validate_runtime(damaged, query_unicode_oracle.ROOT)


@pytest.mark.parametrize('field,value', [('normalization', 16), ('normalization', 17.0),
                                       ('version', [78.0, 2, 0, 0]), ('unicodeVersion', [16, 0, 0, 0]),
                                       ('cldrVersion', [47, 0, 0, 0]), ('manifest', {}), ('libraries', [])])
def test_damaged_library_identity_is_refused(paired, field, value):
    damaged = copy.deepcopy(paired[1])
    damaged['runtime'][field] = value
    with pytest.raises(ValueError):
        query_unicode_oracle.validate_runtime(damaged, query_unicode_oracle.ROOT)


def test_missing_receipt_is_a_deliberate_refusal():
    with pytest.raises(ValueError):
        query_unicode_oracle.validate_runtime(None)


def test_cursor_acceptance_cannot_be_replaced_by_successful_items(paired):
    damaged = copy.deepcopy(paired[1])
    damaged['observations']['cursors'][0]['reversed'] = dict(ids=['beta'])
    with pytest.raises(ValueError, match='cursor boundaries'):
        query_unicode_oracle.validate_runtime(damaged, query_unicode_oracle.ROOT)


@pytest.mark.parametrize('field', ['comparisons', 'fingerprints', 'cursors'])
def test_missing_observation_groups_are_refused(paired, field):
    damaged = copy.deepcopy(paired[1])
    damaged['observations'][field] = []
    with pytest.raises(ValueError):
        query_unicode_oracle.validate_runtime(damaged, query_unicode_oracle.ROOT)
