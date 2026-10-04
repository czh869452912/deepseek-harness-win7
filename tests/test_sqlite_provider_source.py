import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import sqlite_provider_oracle as oracle


ROOT = Path(__file__).resolve().parents[1]
_REPORTS = None


def reports(tmp_path):
    global _REPORTS
    if _REPORTS is None:
        output = tmp_path / 'provider.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sqlite_provider_oracle.py'), '--output', str(output)],
                                cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        summary = json.loads(output.read_text(encoding='utf-8'))
        source = json.loads(output.with_name('provider.source.json').read_text(encoding='utf-8'))
        native = json.loads(output.with_name('provider.native.json').read_text(encoding='utf-8'))
        assert summary['status'] == 'passed' and summary['cases'] == 323
        _REPORTS = summary, source, native
    return copy.deepcopy(_REPORTS)


def test_actual_source_and_native_schema19_mutual_files_and_consumers(tmp_path):
    summary, source, native = reports(tmp_path)
    expected = oracle.source_identity(source)
    oracle.validate_runtime(native, ROOT, expected, summary['generatedInputsSha256'], summary['modules'], summary['assets'])
    assert native['rows'] == source['rows']
    selected = {row['name']: row.get('value') for row in native['rows']}
    assert selected['exact-cross-file-revision'] is True
    assert selected['page-size'] == 65536
    assert selected['cold-inspected'] == 104 and selected['cold-coldPrepared'] == 105
    assert selected['lock-crossProcessBusyCode'] == 5
    assert selected['lock-staleRepairRefused'] is True and selected['lock-winningTailRetained'] is True


@pytest.mark.parametrize('damage', ['root', 'python', 'moduleFile', 'modules', 'assets', 'input',
                                   'source', 'missing', 'duplicate', 'reordered', 'outcome', 'error'])
def test_provider_receipt_refuses_incomplete_or_damaged_source_closure(tmp_path, damage):
    summary, source, native = reports(tmp_path)
    if damage in ('root', 'python', 'moduleFile'):
        native[damage] = 'different'
    elif damage in ('modules', 'assets'):
        native[damage].pop(next(iter(native[damage])))
    elif damage == 'input':
        native['generatedInputsSha256'] = '0' * 64
    elif damage == 'source':
        source['node'] = 'v22.20.0'
    elif damage == 'missing':
        native['rows'].pop()
    elif damage == 'duplicate':
        native['rows'].append(native['rows'][-1])
    elif damage == 'reordered':
        native['rows'][0], native['rows'][1] = native['rows'][1], native['rows'][0]
    elif damage == 'outcome':
        native['rows'][0]['value'] = False
    else:
        row = next(row for row in native['rows'] if 'error' in row)
        row['error'] = dict(message=row['error'])
    with pytest.raises(ValueError):
        oracle.validate_runtime(native, ROOT, oracle.source_identity(source), summary['generatedInputsSha256'], summary['modules'], summary['assets'])
