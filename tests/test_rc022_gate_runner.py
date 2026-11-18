"""Current gate cannot lose an observer or accept a damaged process receipt."""
import copy
import json
import pytest
from scripts import rc022_gate_runner as gate


def test_plan_accounts_for_every_current_observer_and_original_selection():
    plan = gate.load_plan()
    assert len(plan['paired']) == 404 and len(plan['source_tests']) == 476
    assert any(row['script'] == 'scripts/rc022_released_logical_probe.py' for row in plan['paired'])
    assert any(row['script'] == 'scripts/rc022_query_text_probe.py' for row in plan['paired'])
    assert any(row['script'] == 'scripts/rc022_projection_cache_probe.py' for row in plan['paired'])
    assert all((gate.ROOT / row['script']).is_file() for row in plan['paired'])


@pytest.mark.parametrize('damage', ['observer', 'source', 'duplicate', 'path', 'separate'])
def test_plan_rejects_silent_roster_damage(tmp_path, monkeypatch, damage):
    plan = copy.deepcopy(gate.load_plan())
    if damage == 'observer': plan['paired'].pop()
    if damage == 'source': plan['source_tests'].pop()
    if damage == 'duplicate': plan['paired'][-1] = plan['paired'][0]
    if damage == 'path': plan['source_tests'][0] = '../source.spec.ts'
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
