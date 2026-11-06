import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exception_index_is_pinned_and_does_not_reclassify_migration_defects():
    index = json.loads((ROOT / 'migration/upstream-bug-exceptions.json').read_text(encoding='utf-8'))
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    assert index['schema_version'] == 1 and index['target_upstream'] == baseline['target_upstream']
    expected = {'UPSTREAM-REPEAT-001': 1,
        'UPSTREAM-COMPACTION-POLICY-001': 1, 'UPSTREAM-COMPACTION-SUMMARY-001': 1,
        'UPSTREAM-CORDIS-INSPECT-001': 1, 'CORDIS-GUARD-001': 2,
        'CORDIS-RUNTIME-001': 1, 'CORDIS-LIFECYCLE-001': 6, 'UPSTREAM-ACP-PERMISSION-001': 2,
        'UPSTREAM-WINDOWS-ACL-001': 2}
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
        assert row['requalified_upstream'] == baseline['target_upstream']
        assert (ROOT / row['requalification_record']).is_file()
        path = ROOT / row['driver']
        tree = ast.parse(path.read_text(encoding='utf-8'))
        assert any(isinstance(node, ast.FunctionDef) and node.name == row['predicate'] for node in tree.body)
        if 'record' in row:
            assert (ROOT / row['record']).is_file()
            assert len(row['modes']) == len(set(row['modes']))


def test_windows_acl_record_keeps_exact_source_and_port_observations():
    from scripts.windows_acl_oracle import classify

    path = ROOT / 'migration/candidates/rc3/windows-acl-current-checks.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    assert record['status'] == 'targeted-passed-not-release-qualified'
    assert record['finding'] == 'UPSTREAM-WINDOWS-ACL-001'
    assert [row['mode'] for row in record['observations']] == ['this-folder-only', 'protected-null']
    for row in record['observations']:
        assert classify(row['upstream'], row['python']) == row['classification']
        assert row['classification'] == 'reviewed-upstream-bug/UPSTREAM-WINDOWS-ACL-001'
    assert {row['python_architecture'] for row in record['local_raw_runs']} == {'x64', 'x86'}
    assert all(row['exit'] == 0 and row['fixture_removed'] for row in record['local_raw_runs'])
