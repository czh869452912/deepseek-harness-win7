import json
from pathlib import Path

import pytest

from scripts.query_engine_oracle import expected, validate, validate_runtime


@pytest.mark.parametrize('position', range(16))
def test_query_engine_observer_refuses_each_missing_observation(position):
    rows = expected()
    del rows[position]
    with pytest.raises(ValueError):
        validate(rows)


@pytest.mark.parametrize('replacement', [[], {}, None, 'passed', True])
def test_query_engine_observer_refuses_malformed_observations(replacement):
    with pytest.raises(ValueError):
        validate(replacement)


def test_query_engine_observer_refuses_changed_rank_and_hidden_provider():
    rows = expected()
    rows[0]['observed'][0]['seq'] = 1
    with pytest.raises(ValueError):
        validate(rows)
    rows = expected()
    rows[12]['observed'] = rows[0]['observed']
    with pytest.raises(ValueError):
        validate(rows)


@pytest.mark.parametrize('field,replacement', [
    ('root', 'outside-candidate'), ('moduleFile', 'outside-candidate/provider.py'),
    ('python', '3.9.0'), ('sqliteVersion', '3.35.5'),
    ('sqliteSourceId', 'foreign-source'), ('sqliteDllSha256', '0' * 64),
    ('manifest', {}), ('observations', []),
])
def test_query_engine_runtime_refuses_foreign_or_incomplete_provenance(field, replacement):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'dsh/session/bin/sqlite3.json').read_text(encoding='utf-8'))
    report = dict(root=str(root), moduleFile=str(root / 'dsh/session/query_engine.py'),
                  python='3.8.10', sqliteVersion=manifest['version'], sqliteSourceId=manifest['source_id'],
                  sqliteDllSha256=manifest['dll_sha256'], manifest=manifest, observations=expected())
    validate_runtime(report, root)
    report[field] = replacement
    with pytest.raises(ValueError):
        validate_runtime(report, root)


@pytest.mark.parametrize('report', [None, [], True, 'passed', {}])
def test_query_engine_runtime_refuses_malformed_receipts(report):
    with pytest.raises(ValueError):
        validate_runtime(report)
