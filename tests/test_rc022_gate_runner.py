"""Current gate cannot lose an observer or accept a damaged process receipt."""
import copy
import json
import os
import subprocess
import sys
import stat
import pytest
from scripts import rc022_gate_runner as gate


def test_plan_accounts_for_every_current_observer_and_original_selection():
    plan = gate.load_plan()
    assert len(plan['paired']) == 406 and len(plan['source_tests']) == 476
    assert plan['source_test_timeout_ms'] == 30000
    assert plan['source_test_node_version'] == 'v24.13.1'
    assert len(plan['source_platform_exclusions']['win32']) == 2
    assert any(row['script'] == 'scripts/rc022_released_logical_probe.py' for row in plan['paired'])
    assert any(row['script'] == 'scripts/rc022_query_text_probe.py' for row in plan['paired'])
    assert any(row['script'] == 'scripts/rc022_projection_cache_probe.py' for row in plan['paired'])
    assert all((gate.ROOT / row['script']).is_file() for row in plan['paired'])
    # Drivers can construct nested fixture paths or delegate to shared helpers.
    # Every fresh owned output uses the same optional synthetic fixture root.
    assert all('files' in row['disposable_directories'] for row in plan['paired'])


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
    (source / 'vitest.config.ts').write_text("const windowsUnsupportedTests = process.platform === 'win32' ? [] : []", encoding='utf-8')
    plan = dict(source_tests=['case.spec.ts'], source_test_timeout_ms=30000)
    plan['source_platform_exclusions'] = dict(win32=[])
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


@pytest.mark.parametrize('damage', ['none', 'upstream-removed', 'unavailable'])
def test_source_exclusions_require_the_original_windows_config_policy(tmp_path, damage):
    plan = gate.load_plan()
    patterns = [row['upstream_pattern'] for row in plan['source_platform_exclusions']['win32']]
    text = "const windowsUnsupportedTests = process.platform === 'win32' ? [\n" + ''.join("  '" + p + "',\n" for p in patterns) + '] : []'
    if damage == 'upstream-removed': text = text.replace(patterns[0], 'different.spec.ts')
    if damage == 'unavailable': text = 'unknown config'
    (tmp_path / 'vitest.config.ts').write_text(text, encoding='utf-8')
    assert gate.source_exclusions(plan, tmp_path, 'linux') == {}
    if damage == 'none':
        assert set(gate.source_exclusions(plan, tmp_path, 'win32')) == {r['path'] for r in plan['source_platform_exclusions']['win32']}
    else:
        with pytest.raises(ValueError): gate.source_exclusions(plan, tmp_path, 'win32')


@pytest.mark.parametrize('damage', ['none', 'missing', 'expanded', 'failed', 'empty'])
def test_source_lane_accounts_for_original_exclusions_without_accepting_missing_tests(tmp_path, monkeypatch, damage):
    source = tmp_path / 'source'; source.mkdir()
    for name in ['case.spec.ts', 'skip.spec.ts']: (source / name).write_text('', encoding='utf-8')
    (source / 'vitest.config.ts').write_text("const windowsUnsupportedTests = process.platform === 'win32' ? [\n'skip.spec.ts',\n] : []", encoding='utf-8')
    row = dict(path='skip.spec.ts', upstream_pattern='skip.spec.ts', reason='Explicit original policy')
    plan = dict(source_tests=['case.spec.ts', 'skip.spec.ts'], source_test_timeout_ms=30000, source_platform_exclusions=dict(win32=[row]))
    monkeypatch.setattr(gate, 'source_exclusions', lambda *args: {'skip.spec.ts': row})
    def execute(command, cwd, output, name, env, timeout):
        names = [] if damage == 'missing' else ['case.spec.ts']
        if damage == 'expanded': names.append('skip.spec.ts')
        value = dict(success=damage != 'failed', numFailedTests=int(damage == 'failed'),
                     numPassedTests=0 if damage == 'empty' else 1, numPendingTests=0,
                     testResults=[dict(name=str(source / name)) for name in names])
        (output / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')
        return dict(seconds=1)
    monkeypatch.setattr(gate, 'execute', execute)
    operation = lambda: gate.source_lane(plan, source, tmp_path / 'node', tmp_path, {})
    if damage == 'none':
        result = operation()[0]
        assert result['planned_files'] == ['case.spec.ts', 'skip.spec.ts']
        assert result['files'] == ['case.spec.ts'] and result['upstream_platform_exclusions'] == [row]
    else:
        with pytest.raises(ValueError, match='Source cases'): operation()


@pytest.mark.parametrize('declared', [True, False])
def test_actual_paired_entrypoint_imports_siblings_without_pythonpath(tmp_path, monkeypatch, declared):
    package = tmp_path / 'scripts'; package.mkdir()
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'fixture_helper.py').write_text("STATUS = 'passed'\n", encoding='utf-8')
    script = package / 'fixture_probe.py'
    script.write_text('from scripts.fixture_helper import STATUS\n'
        'import argparse,json\nfrom pathlib import Path\n'
        'p=argparse.ArgumentParser();p.add_argument("--source");p.add_argument("--output");a=p.parse_args()\n'
        'out=Path(a.output);out.mkdir();(out/"files").mkdir();(out/"files/payload").write_bytes(b"owned")\n'
        '(out/"report.json").write_text(json.dumps(dict(status=STATUS)),encoding="utf-8")\n', encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if k.upper() not in ['PYTHONPATH', 'PYTHONHOME']}
    # The original direct-file launcher must fail before creating a report.
    direct = subprocess.run([sys.executable, str(script)], cwd=str(tmp_path), env=env,
                            capture_output=True, timeout=10)
    assert direct.returncode != 0 and b"No module named 'scripts'" in direct.stderr
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    output = tmp_path / 'output'; output.mkdir()
    row = dict(script='scripts/fixture_probe.py', node=False, browser=False, timeout_seconds=10,
               receipt='report', disposable_directories=['files'] if declared else [])
    if not declared:
        with pytest.raises(ValueError, match='Undeclared synthetic'):
            gate.paired_lane(dict(paired=[row]), tmp_path / 'source', tmp_path / 'node', tmp_path / 'browser', output, env)
        assert (output / 'fixture_probe/files/payload').read_bytes() == b'owned'
        return
    rows = gate.paired_lane(dict(paired=[row]), tmp_path / 'source', tmp_path / 'node', tmp_path / 'browser', output, env)
    receipt = json.loads((output / 'commands/fixture_probe.json').read_text(encoding='utf-8'))
    assert receipt['command'][:3] == [sys.executable, '-m', 'scripts.fixture_probe']
    assert rows[0]['cleanup'] == dict(removed=['files'], bytes_removed=5)
    assert json.loads((output / 'fixture_probe/report.json').read_text(encoding='utf-8')) == dict(status='passed')


@pytest.mark.parametrize('name', ['.', '..', '../outside', 'files/nested'])
def test_cleanup_refuses_paths_outside_its_declared_root(tmp_path, name):
    output = tmp_path / 'owned'; output.mkdir()
    sentinel = tmp_path / 'keep'; sentinel.write_bytes(b'user data')
    with pytest.raises(ValueError, match='escaped'): gate.retire_success(output, [name])
    assert sentinel.read_bytes() == b'user data'


def test_cleanup_preserves_raw_observations_and_unlinks_without_following_targets(tmp_path):
    output = tmp_path / 'owned'; output.mkdir()
    files = output / 'files'; files.mkdir()
    raw = b'{"raw":"actual observation"}'
    (files / 'capture.json').write_bytes(raw)
    (files / 'fixture.bin').write_bytes(b'synthetic')
    protected = tmp_path / 'protected'; protected.mkdir()
    (protected / 'keep.json').write_bytes(b'outside target')
    link = files / 'external'
    os.symlink(str(protected), str(link), target_is_directory=True)
    result = gate.retire_success(output, ['files'])
    assert result['bytes_removed'] == len(raw) + len(b'synthetic') and not files.exists()
    preserved = output / 'gate-cleanup-observations/files/capture.json'
    assert preserved.read_bytes() == raw
    assert (protected / 'keep.json').read_bytes() == b'outside target'
    inventory = json.loads((output / 'gate-cleanup-inventory.json').read_text(encoding='utf-8'))
    assert dict(path='files/external', kind='reparse') in inventory
    assert not any(row['path'].endswith('keep.json') for row in inventory)
    original = (output / 'gate-cleanup.json').read_bytes()
    with pytest.raises(ValueError, match='already exists'): gate.retire_success(output, ['files'])
    assert (output / 'gate-cleanup.json').read_bytes() == original


@pytest.mark.skipif(os.name != 'nt' or sys.getwindowsversion().major < 10,
                    reason='Modern Windows qualification-host entry unlink')
def test_cleanup_readonly_hardlink_preserves_other_link_attributes_and_bytes(tmp_path):
    source = tmp_path / 'protected.bin'; source.write_bytes(b'shared immutable bytes')
    os.chmod(str(source), stat.S_IREAD)
    output = tmp_path / 'owned'; output.mkdir()
    files = output / 'files'; files.mkdir()
    os.link(str(source), str(files / 'readonly.bin'))
    attributes, checksum = source.stat().st_file_attributes, gate.digest(source)
    try:
        gate.retire_success(output, ['files'])
        assert not files.exists() and source.stat().st_file_attributes == attributes
        assert source.stat().st_file_attributes & 1 and gate.digest(source) == checksum
    finally:
        # This remaining test-owned entry has no consumer after the assertions.
        gate.remove_owned(source)
