import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exception_index_is_pinned_and_does_not_reclassify_migration_defects():
    index = json.loads((ROOT / 'migration/upstream-bug-exceptions.json').read_text(encoding='utf-8'))
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    # The accepted exceptions retain their actual rc.3 qualification identity.
    # Current probes must independently requalify them before any promotion.
    historical_pin = 'a4c74a91e06b00fe0b0937bde982170c526cc842'
    assert index['schema_version'] == 1 and index['target_upstream'] == historical_pin
    assert baseline['target_upstream'] != historical_pin
    expected = {'UPSTREAM-REPEAT-001': 1,
        'UPSTREAM-COMPACTION-POLICY-001': 1, 'UPSTREAM-COMPACTION-SUMMARY-001': 1,
        'UPSTREAM-CORDIS-INSPECT-001': 1, 'CORDIS-GUARD-001': 2,
        'CORDIS-RUNTIME-001': 1, 'CORDIS-LIFECYCLE-001': 6, 'UPSTREAM-ACP-PERMISSION-001': 2}
    assert len(index['exceptions']) == len(expected)
    assert {row['id']: len(row['modes']) for row in index['exceptions']} == expected
    assert index['pending_requalification'] == []
    assert [(row['id'], row['status']) for row in index['retired_exceptions']] == [
        ('UPSTREAM-TOKEN-METER-001', 'resolved-upstream')]
    assert len(index['language_adaptations']) == 1
    adaptation = index['language_adaptations'][0]
    assert adaptation['id'] == 'PY38-RESOLVED-AWAIT' and adaptation['cases'] == ['C58']
    assert adaptation['required_checkpoint'] == 'C59'
    assert any('ACP' in finding for finding in index['excluded_migration_defects'])
    for row in index['exceptions'] + index['language_adaptations']:
        assert row['requalified_upstream'] == historical_pin
        assert (ROOT / row['requalification_record']).is_file()
        path = ROOT / row['driver']
        tree = ast.parse(path.read_text(encoding='utf-8'))
        assert any(isinstance(node, ast.FunctionDef) and node.name == row['predicate'] for node in tree.body)
        if 'record' in row:
            assert (ROOT / row['record']).is_file()
            assert len(row['modes']) == len(set(row['modes']))
