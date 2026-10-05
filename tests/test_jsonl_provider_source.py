import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import jsonl_provider_oracle as oracle

ROOT = Path(__file__).resolve().parents[1]
_REPORTS = None


def reports(tmp_path):
    global _REPORTS
    if _REPORTS is None:
        output = tmp_path / 'jsonl.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/jsonl_provider_oracle.py'), '--output', str(output)],
            cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        summary = json.loads(output.read_text(encoding='utf-8'))
        source = json.loads(output.with_name('jsonl.source.json').read_text(encoding='utf-8'))
        native = json.loads(output.with_name('jsonl.native.json').read_text(encoding='utf-8'))
        assert summary['status'] == 'passed' and summary['cases'] == 579
        _REPORTS = summary, source, native
    return copy.deepcopy(_REPORTS)


def test_actual_source_and_native_compressed_jsonl_mutual_files_and_cold_consumers(tmp_path):
    summary, source, native = reports(tmp_path)
    oracle.validate_runtime(native, ROOT, oracle.source_identity(source), summary['generatedInputsSha256'], summary['modules'], summary['assets'])
    assert native['rows'] == source['rows']
    mutual = [row for row in source['rows'] if row['id'].startswith('mutual/')]
    assert len(mutual) == 4 and all(row['revisionMatched'] and row['unpublished'] for row in mutual)


@pytest.mark.parametrize('damage', ['root', 'python', 'moduleFile', 'modules', 'assets', 'input', 'source', 'missing', 'duplicate', 'reordered', 'outcome'])
def test_jsonl_receipt_refuses_damaged_source_and_owned_file_closure(tmp_path, damage):
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
        native['rows'][-1], native['rows'][-2] = native['rows'][-2], native['rows'][-1]
    else:
        native['rows'][0]['encoded'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.validate_runtime(native, ROOT, oracle.source_identity(source), summary['generatedInputsSha256'], summary['modules'], summary['assets'])
