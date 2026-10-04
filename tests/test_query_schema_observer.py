import copy
from pathlib import Path

import pytest

from scripts.query_schema_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['tail', 'extra', 'reverse', 'unknown', 'strict', 'generation',
    'foreign-write', 'number-bool', 'error', 'data', 'scope'])
def test_query_schema_observer_rejects_damaged_rows(damage):
    rows = expected()
    if damage == 'tail':
        rows.pop()
    elif damage == 'extra':
        rows.append(copy.deepcopy(rows[0]))
    elif damage == 'reverse':
        rows.reverse()
    elif damage == 'unknown':
        rows[0]['unknown'] = True
    elif damage == 'strict':
        rows[0]['observed']['strict'][0]['strict'] = 0
    elif damage == 'number-bool':
        rows[0]['observed']['strict'][0]['strict'] = True
    else:
        indexed = {row['name']: row['observed'] for row in rows}
        if damage == 'generation':
            indexed['upgrade']['generation'] = 7
        elif damage == 'foreign-write':
            indexed['foreign-app']['unchanged'] = False
        elif damage == 'error':
            indexed['strict-type']['code'] = 0
        elif damage == 'data':
            indexed['memory-documents']['matches'] = []
        else:
            indexed['live-scope']['live'] = 1
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('damage', ['root', 'module', 'python', 'extra', 'version', 'source-id', 'dll', 'hash', 'missing-sqlite'])
def test_query_schema_observer_requires_exact_runtime(tmp_path, damage):
    report = dict(observations=expected(), root=str(tmp_path), module=str(tmp_path / 'dsh/__init__.py'),
        python=[3, 8, 10], sqlite=dict(version='3.51.2',
            sourceId='2026-01-09 17:27:48 b270f8339eb13b504d0b2ba154ebca966b7dde08e40c3ed7d559749818cb2075',
            dll=str(tmp_path / 'dsh/session/bin/sqlite3.dll'),
            sha256='2339b9e7c8b2d4be67d5516fed37aa70c02bdb463386c47ab130d00586751642'))
    validate_runtime(report)
    if damage == 'root':
        report['root'] = 'relative'
    elif damage == 'module':
        report['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        report['python'] = [3, 9, 0]
    elif damage == 'extra':
        report['unknown'] = True
    elif damage == 'missing-sqlite':
        del report['sqlite']
    else:
        key = {'version': 'version', 'source-id': 'sourceId', 'dll': 'dll', 'hash': 'sha256'}[damage]
        report['sqlite'][key] = 'foreign'
    with pytest.raises(ValueError):
        validate_runtime(report)
