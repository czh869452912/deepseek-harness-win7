import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import jsonl_provider_oracle as oracle
from evidence_fixtures import read_member
from release_gate_fixtures import synthetic_native_model

ROOT = Path(__file__).resolve().parents[1]
_REPORTS = None


def reports(tmp_path):
    global _REPORTS
    if _REPORTS is None:
        # Synthetic parser values derived from immutable historical facts.
        # Actual current physical readers have distinct Node24/v4 contracts.
        archive = 'RC3-QUALIFICATION-20261018-228CFACC.zip'
        source = read_member(archive, 'full-gate-root.zip!/jsonl-provider-paired.source.json')
        native = synthetic_native_model('full-gate-root.zip!/jsonl-provider-paired.native.json', oracle.MODULES, exact=True)
        native['root'] = str(ROOT)
        native['moduleFile'] = str(ROOT / 'dsh/session/jsonl_backend_current.py')
        summary = dict(status='parser-model', cases=1030, generatedInputsSha256=native['generatedInputsSha256'],
                       modules=copy.deepcopy(native['modules']), assets=copy.deepcopy(native['assets']))
        oracle.source_identity(source)
        _REPORTS = summary, source, native
    return copy.deepcopy(_REPORTS)


def test_historical_jsonl_receipt_parser_with_immutable_source_values(tmp_path):
    summary, source, native = reports(tmp_path)
    oracle.validate_runtime(native, ROOT, oracle.source_identity(source), summary['generatedInputsSha256'], summary['modules'], summary['assets'])
    assert native['rows'] == source['rows']
    mutual = [row for row in source['rows'] if row['id'].startswith('mutual/')]
    assert len(mutual) == 4 and all(row['revisionMatched'] and row['access'] == 'read' for row in mutual)


@pytest.mark.parametrize('damage', ['root', 'python', 'moduleFile', 'modules', 'assets', 'input', 'source', 'missing', 'duplicate', 'reordered', 'outcome', 'metadata-omit', 'metadata-changed', 'metadata-mutated', 'metadata-reordered'])
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
    elif damage == 'metadata-omit':
        del native['rows'][579]
    elif damage == 'metadata-changed':
        native['rows'][579]['metadata']['value']['createdAt'] = 2
    elif damage == 'metadata-mutated':
        native['rows'][580]['unchanged'] = False
    elif damage == 'metadata-reordered':
        native['rows'][580], native['rows'][581] = native['rows'][581], native['rows'][580]
    else:
        native['rows'][0]['encoded'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.validate_runtime(native, ROOT, oracle.source_identity(source), summary['generatedInputsSha256'], summary['modules'], summary['assets'])
