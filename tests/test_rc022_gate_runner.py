"""Current gate cannot lose an observer or accept a damaged process receipt."""
import copy
import json
import pytest
from scripts import rc022_gate_runner as gate


def test_plan_accounts_for_every_current_observer_and_original_selection():
    plan = gate.load_plan()
    assert len(plan['paired']) == 406 and len(plan['source_tests']) == 476
    assert plan['source_test_timeout_ms'] == 30000
    assert plan['source_test_node_version'] == 'v24.13.1'
    assert any(row['script'] == 'scripts/rc022_released_logical_probe.py' for row in plan['paired'])
    assert any(row['script'] == 'scripts/rc022_query_text_probe.py' for row in plan['paired'])
    assert any(row['script'] == 'scripts/rc022_projection_cache_probe.py' for row in plan['paired'])
    assert all((gate.ROOT / row['script']).is_file() for row in plan['paired'])


@pytest.mark.parametrize('damage', ['observer', 'source', 'duplicate', 'path', 'separate', 'source-runtime'])
def test_plan_rejects_silent_roster_damage(tmp_path, monkeypatch, damage):
    plan = copy.deepcopy(gate.load_plan())
    if damage == 'observer': plan['paired'].pop()
    if damage == 'source': plan['source_tests'].pop()
    if damage == 'duplicate': plan['paired'][-1] = plan['paired'][0]
    if damage == 'path': plan['source_tests'][0] = '../source.spec.ts'
    if damage == 'source-runtime': plan['source_test_node_version'] = 'v24.9.0'
    if damage == 'separate':
        row = plan['paired'].pop()
        plan['separate'].append(dict(script=row['script'], reason='silently skipped'))
    path = tmp_path / 'plan.json'; path.write_text(json.dumps(plan), encoding='utf-8')
    monkeypatch.setattr(gate, 'PLAN', path)
    with pytest.raises(ValueError): gate.load_plan()


@pytest.mark.parametrize('value', [
    dict(difference_count=1, source_rows=1, native_rows=1),
    dict(difference_count=False, source_rows=1, native_rows=1),
    dict(difference_count=0, source_rows=0, native_rows=0),
    dict(difference_count=0, source_rows=1, native_rows=True),
    dict(difference_count=0, source_rows=2, native_rows=1),
    dict(difference_count=0, source_rows=1, native_rows=1, source_exit_code=1),
])
def test_paired_summary_rejects_failure_empty_counts_and_boolean_numbers(tmp_path, value):
    (tmp_path / 'summary.json').write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError): gate.validate_pair(dict(receipt='summary'), tmp_path)


def test_upload_receipt_does_not_equate_false_to_zero(tmp_path):
    value = dict(all_equal=True, count=1, rows=[dict(equal=True, source=dict(x=False), native=dict(x=0))])
    (tmp_path / 'report.json').write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError): gate.validate_pair(dict(receipt='all_equal'), tmp_path)


def test_cleanup_only_retires_declared_owned_assets(tmp_path):
    (tmp_path / 'payload').mkdir(); (tmp_path / 'payload/fixture').write_bytes(b'owned')
    observation = tmp_path / 'source.json'; observation.write_text('{}', encoding='utf-8')
    result = gate.retire_success(tmp_path, ['payload'])
    assert result == dict(removed=['payload'], bytes_removed=5)
    assert observation.read_text(encoding='utf-8') == '{}'


def test_cleanup_failure_retains_completed_process_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'run_observer', lambda *args, **kwargs: 0)
    workspace = tmp_path / 'temporary'; workspace.mkdir()
    monkeypatch.setattr(gate.tempfile, 'mkdtemp', lambda **kwargs: str(workspace))
    def locked(path):
        raise PermissionError('owned file remains locked')
    monkeypatch.setattr(gate, 'remove_owned', locked)
    with pytest.raises(PermissionError, match='remains locked'):
        gate.execute(['fixture'], tmp_path, tmp_path, 'fixture', {}, 1)
    receipt = json.loads((tmp_path / 'commands/fixture.json').read_text(encoding='utf-8'))
    assert receipt['completed'] and receipt['exit_code'] == 0
    assert receipt['workspace'] == str(workspace)
    assert 'remains locked' in receipt['cleanup_error']


@pytest.mark.parametrize('budget', [None, True, 0, 999, 120001, '30000'])
def test_plan_rejects_missing_or_unbounded_source_budget(tmp_path, monkeypatch, budget):
    plan = copy.deepcopy(gate.load_plan())
    plan['source_test_timeout_ms'] = budget
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(plan), encoding='utf-8')
    monkeypatch.setattr(gate, 'PLAN', path)
    with pytest.raises(ValueError, match='Source shared-host'): gate.load_plan()


def test_source_lane_uses_pinned_upstream_budget_and_keeps_failure_diagnostics(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'case.spec.ts').write_text('', encoding='utf-8')
    plan = dict(source_tests=['case.spec.ts'], source_test_timeout_ms=30000)
    environment = dict(DSH_COVERAGE_TEST_TIMEOUT_MS='1')
    def execute(command, cwd, output, name, env, timeout):
        assert env['DSH_COVERAGE_TEST_TIMEOUT_MS'] == '30000'
        assert env['PATH'].startswith(str(tmp_path))
        assert '--reporter=default' in command and '--reporter=json' in command
        assert timeout == 900
        (output / (name + '.json')).write_text(json.dumps(dict(success=True,
            numFailedTests=0, numPassedTests=1, numPendingTests=0,
            testResults=[dict(name=str(source / 'case.spec.ts'))])), encoding='utf-8')
        return dict(seconds=7)
    monkeypatch.setattr(gate, 'execute', execute)
    rows = gate.source_lane(plan, source, tmp_path / 'node', tmp_path, environment)
    assert rows[0]['test_timeout_ms'] == 30000
    assert environment == dict(DSH_COVERAGE_TEST_TIMEOUT_MS='1')


@pytest.mark.parametrize('version', ['v24.9.0', 'v24.13.1', 'v25.0.0'])
def test_source_test_runtime_is_distinct_and_pinned(tmp_path, monkeypatch, version):
    node = tmp_path / 'node.exe'; node.write_bytes(b'actual selected executable')
    monkeypatch.setattr(gate.subprocess, 'check_output', lambda *args, **kwargs: version + '\n')
    plan = gate.load_plan()
    if version == 'v24.13.1': assert gate.source_test_runtime(plan, node) == node
    else:
        with pytest.raises(ValueError, match='Source test runtime'): gate.source_test_runtime(plan, node)
