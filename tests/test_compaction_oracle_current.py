"""Historical reviewed defects keep their exact original inputs and identity."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.compaction_oracle import (BUG_TARGET, BUG_CASE, SUMMARY_BUG_CASE,
    reviewed_route_key_difference, reviewed_summary_metadata_difference)
from evidence_fixtures import read_member

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def captured(tmp_path_factory):
    output = tmp_path_factory.mktemp('current-compaction') / 'report.json'
    result = subprocess.run([sys.executable, 'scripts/oracles/compaction_python.py', str(output)],
                            cwd=str(ROOT), capture_output=True, timeout=90)
    output.with_suffix('.runner.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    native = {row['mode']: row for row in json.loads(output.read_text(encoding='utf-8'))}
    source = read_member('RC3-QUALIFICATION-20261018-228CFACC.zip',
                         'full-gate-root.zip!/compaction-paired.ts.json')
    return {row['mode']: dict(status='reviewed-upstream-bug', upstream=row, python=native[row['mode']])
            for row in source if row['mode'] in ('embedded-nul-routes', 'transaction-private-fields')}


@pytest.mark.parametrize('mode,recipe,check', [
    ('embedded-nul-routes', BUG_CASE, reviewed_route_key_difference),
    ('transaction-private-fields', SUMMARY_BUG_CASE, reviewed_summary_metadata_difference),
])
def test_historical_defects_require_exact_input_output_and_pin(captured, mode, recipe, check):
    row = captured[mode]
    assert row['status'] == 'reviewed-upstream-bug'
    left, right = row['upstream'], row['python']
    assert check(left, right, recipe, BUG_TARGET)
    assert not check(left, right, recipe, 'a66e4702047846cdaa10c66c9d3df3951f5ea70d')
    assert not check(left, right, dict(recipe, unknown=True), BUG_TARGET)
    for side in ['upstream', 'python']:
        changed = copy.deepcopy(row)
        changed[side]['unobserved'] = True
        assert not check(changed['upstream'], changed['python'], recipe, BUG_TARGET)
    assert not check(right, right, recipe, BUG_TARGET)


def test_private_metadata_exception_preserves_system_head_and_exact_shadow_span(captured):
    row = captured['transaction-private-fields']
    for path, value in [('text', 'changed prefix'), ('keys', 'system')]:
        changed = copy.deepcopy(row['python'])
        changed['inputs'][0][path][0] = value
        assert not reviewed_summary_metadata_difference(row['upstream'], changed, SUMMARY_BUG_CASE, BUG_TARGET)
    changed = copy.deepcopy(row['python'])
    changed['nodes'].pop(0)
    assert not reviewed_summary_metadata_difference(row['upstream'], changed, SUMMARY_BUG_CASE, BUG_TARGET)
