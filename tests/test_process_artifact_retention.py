import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest


from scripts import process_artifact_retention as retention


MODULE = Path(retention.__file__)


def completed(tmp_path):
    root = tmp_path / '.goose/out'
    output = root / 'candidate'
    workspace = output / 'pytest-workspace'
    workspace.mkdir(parents=True)
    (output / 'pytest-workspace-mapping.json').write_text(json.dumps(dict(execution_path=str(root / 'g-finished'), retained_path=str(workspace))), encoding='utf-8')
    (output / 'pytest.xml').write_text('<testsuites><testsuite tests="1" failures="0" errors="0"><testcase name="actual"/></testsuite></testsuites>', encoding='utf-8')
    return root, output, workspace


def receipt(workspace, label='test_control0', name='receipt.json', runtime=None):
    folder = workspace / label
    folder.mkdir(exist_ok=True)
    (folder / 'portable.zip').write_bytes(retention.FAKE_ARCHIVE)
    selected = folder / name
    selected.write_text(json.dumps(dict(runtime=dict(checks=['actual runtime']) if runtime is None else runtime)), encoding='utf-8')
    return selected


@pytest.mark.parametrize('name', ['receipt.json', 'extracted.json'])
def test_finished_test_folder_prunes_only_its_own_synthetic_outputs(tmp_path, name):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace, name=name)
    other = receipt(workspace, label='test_still_active0')
    real = selected.parent / 'actual-source.json'
    real.write_text('{"source":"retained"}', encoding='utf-8')
    result = retention.prune_finished_test_folder(root, workspace, selected.parent)
    assert result['removed_files'] == 1
    assert not selected.exists() and other.exists()
    assert real.read_text(encoding='utf-8') == '{"source":"retained"}'
    audit = json.loads((selected.parent / 'unit-receipts-pruned.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'completed' and audit['expected_files'] == 1
    assert (output / 'pytest.xml').exists()


@pytest.mark.parametrize('damage', ['external', 'nested', 'wrong-owner', 'real-zip', 'unknown-runtime'])
def test_finished_test_folder_preserves_unowned_or_real_outputs(tmp_path, damage):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    owner = workspace
    if damage == 'external':
        root = tmp_path / 'other-root'
        root.mkdir()
    elif damage == 'nested':
        owner = workspace.parent
    elif damage == 'wrong-owner':
        owner = workspace / 'test_other0'
        owner.mkdir()
    elif damage == 'real-zip':
        (selected.parent / 'portable.zip').write_bytes(b'PK actual archive')
    else:
        selected.write_text('{"runtime":{"checks":["original Source"]}}', encoding='utf-8')
    before = selected.read_bytes()
    result = retention.prune_finished_test_folder(root, owner, selected.parent)
    assert result is None or result['removed_files'] == 0
    assert selected.read_bytes() == before


@pytest.mark.parametrize('name', ['receipt.json', 'extracted.json'])
def test_finished_synthetic_receipts_are_pruned_with_bounded_audit(tmp_path, name):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace, name=name)
    expected = selected.stat().st_size
    result = retention.prune_completed_regression(root, output)
    assert result['removed_files'] == 1 and result['removed_bytes'] == expected
    assert not selected.exists() and (selected.parent / 'portable.zip').read_bytes() == retention.FAKE_ARCHIVE
    assert (output / 'pytest.xml').is_file()
    audit = json.loads((output / 'unit-receipts-pruned.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'completed' and audit['expected_files'] == 1
    assert retention.prune_completed_regression(root, output)['removed_files'] == 0
    assert json.loads((output / 'unit-receipts-pruned.json').read_text(encoding='utf-8')) == audit


@pytest.mark.parametrize('placement', ['owned', 'external'])
@pytest.mark.parametrize('outcome', ['passed', 'failed'])
def test_actual_gate_teardown_prunes_finished_test_before_next_test(tmp_path, placement, outcome):
    root = Path(__file__).resolve().parents[1]
    child = tmp_path / 'gate-teardown'
    child.mkdir()
    temporary_parent = Path(tempfile.gettempdir()).resolve()
    workspace = Path(tempfile.mkdtemp(prefix='g-' if placement == 'owned' else 'gate-external-')).resolve()
    environment = dict(os.environ)
    owner = None
    if placement == 'owned':
        output_root = (root / '.goose/out').resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        owner = Path(tempfile.mkdtemp(prefix='nested-gate-owner-', dir=str(output_root))).resolve()
        mapping = dict(format='dsh-release-workspace@2', temporary_parent=str(temporary_parent),
                       execution_path=str(workspace), retained_path=str(owner / 'pytest-workspace'))
        (owner / 'pytest-workspace-mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
        (child / 'workspace-mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
        environment['DSH_RELEASE_PYTEST_OUTPUT'] = str(owner)
    record = child / 'first.txt'
    script = child / 'test_teardown.py'
    script.write_text(
        "import json\nimport sys\nfrom pathlib import Path\n"
        + "sys.path.insert(0, " + repr(str(root)) + ")\n"
        + "sys.path.insert(0, " + repr(str(root / 'tests')) + ")\n"
        + "from test_current_release_gate import prune_completed_gate_test\n"
        + "RECORD = Path(" + repr(str(record)) + ")\n"
        + "def test_first(tmp_path):\n"
        + "    (tmp_path / 'portable.zip').write_bytes(b'exact candidate archive')\n"
        + "    (tmp_path / 'receipt.json').write_text(json.dumps({'runtime': {'checks': ['actual runtime']}}), encoding='utf-8')\n"
        + "    (tmp_path / 'actual-source.json').write_text('retained', encoding='utf-8')\n"
        + "    RECORD.write_text(str(tmp_path), encoding='utf-8')\n"
        + "    assert (tmp_path / 'receipt.json').exists()\n"
        + ("    assert False, 'retained original failure'\n" if outcome == 'failed' else '')
        + "def test_second(tmp_path):\n"
        + "    previous = Path(RECORD.read_text(encoding='utf-8'))\n"
        + "    assert (previous / 'receipt.json').exists() is " + str(placement == 'external') + "\n"
        + "    assert (previous / 'actual-source.json').read_text(encoding='utf-8') == 'retained'\n"
        + "    assert (previous / 'portable.zip').read_bytes() == b'exact candidate archive'\n"
        + ("    assert json.loads((previous / 'unit-receipts-pruned.json').read_text(encoding='utf-8'))['status'] == 'completed'\n" if placement == 'owned' else ''),
        encoding='utf-8')
    qualified = False
    try:
        result = subprocess.run([sys.executable, '-m', 'pytest', str(script), '-q',
            '--confcutdir=' + str(child), '--basetemp=' + str(workspace), '--junitxml=' + str(child / 'pytest.xml')],
            cwd=str(root), env=environment, capture_output=True, timeout=60)
        (child / 'pytest.log').write_bytes(result.stdout + result.stderr)
        assert result.returncode == (1 if outcome == 'failed' else 0), result.stdout + result.stderr
        cases = ET.parse(str(child / 'pytest.xml')).findall('.//testcase')
        assert [case.get('name') for case in cases] == ['test_first', 'test_second']
        assert all(case.find('error') is None and case.find('skipped') is None for case in cases)
        assert (cases[0].find('failure') is not None) is (outcome == 'failed')
        assert cases[1].find('failure') is None, result.stdout + result.stderr
        if outcome == 'failed':
            assert b'retained original failure' in result.stdout
            assert 'retained original failure' in (child / 'pytest.xml').read_text(encoding='utf-8')
        qualified = True
    finally:
        if qualified:
            assert workspace.resolve() == workspace and workspace.parent == temporary_parent
            assert workspace.name.startswith('g-' if placement == 'owned' else 'gate-external-')
            for parent, directories, names in os.walk(str(workspace), followlinks=False):
                for path in [Path(parent)] + [Path(parent) / name for name in directories + names]:
                    assert not path.is_symlink() and not getattr(path.lstat(), 'st_file_attributes', 0) & 0x400
            shutil.rmtree(str(workspace))
            if owner is not None:
                assert owner.resolve() == owner and owner.parent == (root / '.goose/out').resolve()
                assert {path.name for path in owner.iterdir()} == {'pytest-workspace-mapping.json'}
                assert not getattr(owner.lstat(), 'st_file_attributes', 0) & 0x400
                shutil.rmtree(str(owner))
            (child / 'workspace-pruned.json').write_text(json.dumps(dict(status='completed',
                workspace=str(workspace), owner=str(owner) if owner else None, physicalExit=result.returncode,
                scope='Only this physically exited child fixture workspace; XML/logs/script retained.')), encoding='utf-8')


@pytest.mark.parametrize('damage', ['real-zip', 'foreign-runtime', 'missing-runtime', 'invalid-json', 'unknown-name', 'nested-folder', 'unowned-folder'])
def test_unclassified_or_real_artifacts_are_preserved(tmp_path, damage):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    if damage == 'real-zip':
        (selected.parent / 'portable.zip').write_bytes(b'PK actual archive')
    elif damage == 'foreign-runtime':
        selected.write_text('{"runtime":{"checks":["real observation"]}}', encoding='utf-8')
    elif damage == 'missing-runtime':
        selected.write_text('{}', encoding='utf-8')
    elif damage == 'invalid-json':
        selected.write_text('{', encoding='utf-8')
    elif damage == 'unknown-name':
        selected.rename(selected.with_name('actual-source.json'))
        selected = selected.with_name('actual-source.json')
    elif damage == 'nested-folder':
        nested = selected.parent / 'nested'
        nested.mkdir()
        selected.rename(nested / selected.name)
        selected = nested / selected.name
    else:
        selected.parent.rename(workspace / 'user-data')
        selected = workspace / 'user-data/receipt.json'
    before = selected.read_bytes()
    assert retention.prune_completed_regression(root, output)['removed_files'] == 0
    assert selected.read_bytes() == before


@pytest.mark.parametrize('damage', ['active', 'missing-xml', 'incomplete-xml', 'foreign-execution', 'foreign-retained'])
def test_active_or_unowned_workspaces_are_refused(tmp_path, damage):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    mapping = output / 'pytest-workspace-mapping.json'
    values = json.loads(mapping.read_text(encoding='utf-8'))
    if damage == 'active':
        (root / 'g-finished').mkdir()
    elif damage == 'missing-xml':
        (output / 'pytest.xml').unlink()
    elif damage == 'incomplete-xml':
        (output / 'pytest.xml').write_text('<testsuite tests="2"><testcase/></testsuite>', encoding='utf-8')
    elif damage == 'foreign-execution':
        values['execution_path'] = str(tmp_path / 'g-foreign')
    else:
        values['retained_path'] = str(tmp_path)
    mapping.write_text(json.dumps(values), encoding='utf-8')
    with pytest.raises((ValueError, OSError)):
        retention.prune_completed_regression(root, output)
    assert selected.exists()


def test_missing_runtime_negative_fixture_is_still_synthetic(tmp_path):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    selected.write_text('{"runtime":null}', encoding='utf-8')
    assert retention.prune_completed_regression(root, output)['removed_files'] == 1


def test_changed_file_is_preserved_and_partial_failure_is_audited(tmp_path, monkeypatch):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    original = retention.candidate
    calls = []

    def changed_candidate(output_root, path, expected=None):
        if Path(path) == selected:
            calls.append(path)
            if len(calls) == 2:
                selected.write_text('{"runtime":{"checks":["real observation"]}}', encoding='utf-8')
        return original(output_root, path, expected=expected)

    monkeypatch.setattr(retention, 'candidate', changed_candidate)
    with pytest.raises(RuntimeError, match='changed before cleanup'):
        retention.prune_completed_regression(root, output)
    assert selected.exists()
    audit = json.loads((output / 'unit-receipts-pruned.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'failed' and audit['removed_files'] == 0


@pytest.mark.parametrize('status', ['planned', 'failed'])
def test_interrupted_cleanup_resumes_without_rewriting_previous_audit(tmp_path, status):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    audit = output / 'unit-receipts-pruned.json'
    previous = json.dumps(dict(status=status, expected_files=1, removed_files=0))
    audit.write_text(previous, encoding='utf-8')
    result = retention.prune_completed_regression(root, output)
    assert result['removed_files'] == 1 and not selected.exists()
    assert audit.read_text(encoding='utf-8') == previous
    resumed = json.loads((output / 'unit-receipts-pruned-retry-1.json').read_text(encoding='utf-8'))
    assert resumed['status'] == 'completed' and resumed['removed_files'] == 1


def test_synthetic_content_is_parsed_once_but_rechecked_before_deletion(tmp_path, monkeypatch):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    original = retention.json.loads
    parsed = []

    def observe(value, *arguments, **options):
        if 'actual runtime' in value:
            parsed.append(value)
        return original(value, *arguments, **options)

    monkeypatch.setattr(retention.json, 'loads', observe)
    assert retention.prune_completed_regression(root, output)['removed_files'] == 1
    assert len(parsed) == 1 and not selected.exists()


def test_junction_or_symlink_never_deletes_foreign_receipts(tmp_path):
    root, output, workspace = completed(tmp_path)
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    selected = receipt(foreign)
    link = workspace / 'test_alias0'
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(selected.parent)], capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        link.symlink_to(selected.parent, target_is_directory=True)
    assert retention.prune_completed_regression(root, output)['removed_files'] == 0
    assert selected.exists()


def test_audit_examples_are_bounded(tmp_path):
    root, output, workspace = completed(tmp_path)
    for index in range(40):
        receipt(workspace, label='test_control' + str(index))
    result = retention.prune_completed_regression(root, output)
    assert result['removed_files'] == 40 and len(result['examples']) == 32


def test_startup_cleanup_ignores_unfinished_outputs(tmp_path):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    assert retention.prune_previous_regressions(root) == []
    assert selected.exists()
    (output / 'summary.json').write_text('{"result":"passed"}', encoding='utf-8')
    reports = retention.prune_previous_regressions(root)
    assert len(reports) == 1 and reports[0]['removed_files'] == 1


@pytest.mark.parametrize('status', [2, 3, 4, 5, False])
def test_unfinished_pytest_sessions_are_not_pruned(tmp_path, status):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    session = SimpleNamespace(config=SimpleNamespace(_tmp_path_factory=SimpleNamespace(_basetemp=workspace)))
    assert retention.prune_pytest_session(session, status, root) is None
    assert selected.exists()


@pytest.mark.parametrize('placement', ['owned', 'default', 'external'])
@pytest.mark.parametrize('outcome', ['passed', 'failed'])
def test_actual_pytest_end_hook_prunes_synthetic_data_and_preserves_diagnostics(tmp_path, outcome, placement):
    child = tmp_path / 'child'
    child.mkdir()
    output_root = child / '.goose/out'
    output_root.mkdir(parents=True)
    scripts = child / 'scripts'
    scripts.mkdir()
    (scripts / '__init__.py').write_text('', encoding='utf-8')
    (scripts / 'process_artifact_retention.py').write_bytes(MODULE.read_bytes())
    test_folder = child / 'tests'
    test_folder.mkdir()
    (test_folder / 'conftest.py').write_bytes(Path(__file__).with_name('conftest.py').read_bytes())
    (test_folder / 'test_process.py').write_text(
        "def test_process(tmp_path):\n"
        "    (tmp_path / 'portable.zip').write_bytes(b'exact candidate archive')\n"
        "    (tmp_path / 'receipt.json').write_text('{\"runtime\":{\"checks\":[\"actual runtime\"]}}', encoding='utf-8')\n"
        "    (tmp_path / 'actual-source.json').write_text('{\"source\":\"retained\"}', encoding='utf-8')\n"
        "    from pathlib import Path\n"
        "    (Path(__file__).resolve().parents[1] / 'workspace.txt').write_text(str(tmp_path.parent), encoding='utf-8')\n"
        + ("    assert False, 'retained failure diagnosis'\n" if outcome == 'failed' else ''), encoding='utf-8')
    arguments = [sys.executable, '-m', 'pytest', str(test_folder / 'test_process.py'), '-q',
        '--junitxml=' + str(child / 'pytest.xml')]
    if placement != 'default':
        arguments.append('--basetemp=' + str(output_root / 'g-own' if placement == 'owned' else child / 'external'))
    result = subprocess.run(arguments,
        cwd=str(child), capture_output=True, timeout=60)
    assert result.returncode == (0 if outcome == 'passed' else 1), result.stdout + result.stderr
    workspace = Path((child / 'workspace.txt').read_text(encoding='utf-8'))
    assert list(workspace.glob('test_process*/actual-source.json'))
    assert (child / 'pytest.xml').is_file()
    if outcome == 'failed':
        assert b'retained failure diagnosis' in result.stdout
    if placement == 'external':
        assert workspace == child / 'external'
        assert list(workspace.glob('test_process*/receipt.json'))
        assert not (workspace / 'unit-receipts-pruned.json').exists()
        return
    assert workspace.parent == output_root
    assert workspace.name.startswith('t-') if placement == 'default' else workspace.name == 'g-own'
    assert not list(workspace.glob('test_process*/receipt.json'))
    audit = json.loads((workspace / 'unit-receipts-pruned.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'completed' and audit['removed_files'] == 1


def test_default_pytest_workspaces_are_unique_and_preserve_previous_outputs(tmp_path):
    root = tmp_path / '.goose/out'
    config = SimpleNamespace(option=SimpleNamespace(basetemp=None))
    first = retention.configure_pytest_workspace(config, root)
    retained = first / 'actual-source.json'
    retained.write_text('{"source":"retained"}', encoding='utf-8')
    second_config = SimpleNamespace(option=SimpleNamespace(basetemp=None))
    second = retention.configure_pytest_workspace(second_config, root)
    assert first != second and first.parent == second.parent == root
    assert config.option.basetemp == str(first) and second_config.option.basetemp == str(second)
    assert retained.read_text(encoding='utf-8') == '{"source":"retained"}'
    assert retention.configure_pytest_workspace(config, root) is None
    assert retained.exists()


@pytest.mark.parametrize('status', [0, 1])
def test_verified_release_owner_defers_only_its_actual_pytest_workspace(tmp_path, monkeypatch, status):
    root = tmp_path / '.goose/out'
    output = root / 'release'
    workspace = root / 'g-current'
    output.mkdir(parents=True)
    workspace.mkdir()
    selected = receipt(workspace)
    (output / 'pytest-workspace-mapping.json').write_text(json.dumps(dict(execution_path=str(workspace),
        retained_path=str(output / 'pytest-workspace'))), encoding='utf-8')
    monkeypatch.setenv('DSH_RELEASE_PYTEST_OUTPUT', str(output))
    session = SimpleNamespace(config=SimpleNamespace(_tmp_path_factory=SimpleNamespace(_basetemp=workspace)))
    result = retention.prune_pytest_session(session, status, root)
    assert result == dict(status='deferred', owner=str(output), workspace=str(workspace), exitstatus=status)
    assert selected.exists() and not (workspace / 'unit-receipts-pruned.json').exists()


@pytest.mark.parametrize('owner', ['external', 'different-workspace'])
def test_inherited_release_owner_cannot_defer_nested_pytest_cleanup(tmp_path, monkeypatch, owner):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    if owner == 'external':
        monkeypatch.setenv('DSH_RELEASE_PYTEST_OUTPUT', str(tmp_path / 'parent-release'))
    else:
        execution = root / 'g-parent'
        execution.mkdir()
        (output / 'pytest-workspace-mapping.json').write_text(json.dumps(dict(execution_path=str(execution),
            retained_path=str(output / 'pytest-workspace'))), encoding='utf-8')
        monkeypatch.setenv('DSH_RELEASE_PYTEST_OUTPUT', str(output))
    session = SimpleNamespace(config=SimpleNamespace(_tmp_path_factory=SimpleNamespace(_basetemp=workspace)))
    result = retention.prune_pytest_session(session, 0, root)
    assert result['removed_files'] == 1 and not selected.exists()


def test_explicit_pytest_workspace_is_preserved_without_creating_an_output_root(tmp_path):
    explicit = tmp_path / 'user-temp'
    config = SimpleNamespace(option=SimpleNamespace(basetemp=str(explicit)))
    root = tmp_path / '.goose/out'
    assert retention.configure_pytest_workspace(config, root) is None
    assert config.option.basetemp == str(explicit)
    assert not root.exists()


def test_expired_cleanup_manifests_keep_latest_two_and_pending_data(tmp_path):
    root, output, workspace = completed(tmp_path)
    folder = root / 'acp-a4-work'
    folder.mkdir()
    pending = receipt(workspace)
    for index in range(1, 6):
        path = folder / ('unit-receipt-cleanup-candidates-v' + str(index) + '.json')
        path.write_text(json.dumps(dict(files=1, candidates=[dict(path=str(root / ('test_old' + str(index)) / 'receipt.json'))])), encoding='utf-8')
        os.utime(str(path), (index, index))
    live = folder / 'unit-receipt-cleanup-candidates-v6.json'
    live.write_text(json.dumps(dict(files=1, candidates=[dict(path=str(pending))])), encoding='utf-8')
    removed = retention.expire_finished_manifests(root, folder)
    assert len(removed) == 3 and live.exists() and pending.exists()
    assert sorted(path.name for path in folder.iterdir()) == [
        'unit-receipt-cleanup-candidates-v4.json', 'unit-receipt-cleanup-candidates-v5.json', 'unit-receipt-cleanup-candidates-v6.json']


@pytest.mark.parametrize('damage', ['outside', 'invalid-json', 'unknown-name', 'count', 'root-list'])
def test_unclassified_cleanup_manifests_are_preserved(tmp_path, damage):
    root, output, workspace = completed(tmp_path)
    folder = root / 'acp-a4-work'
    folder.mkdir()
    path = folder / 'unit-receipt-cleanup-candidates-v1.json'
    if damage == 'invalid-json':
        path.write_text('{', encoding='utf-8')
    elif damage == 'root-list':
        path.write_text('[]', encoding='utf-8')
    else:
        path.write_text(json.dumps(dict(files=2 if damage == 'count' else 1,
            candidates=[dict(path=str(tmp_path / 'foreign/receipt.json' if damage == 'outside' else root / 'missing/receipt.json'))])), encoding='utf-8')
    if damage == 'unknown-name':
        path.rename(folder / 'actual-source.json')
        path = folder / 'actual-source.json'
    before = path.read_bytes()
    assert retention.expire_finished_manifests(root, folder) == []
    assert path.read_bytes() == before


@pytest.mark.parametrize('status', ['finished', 'active', 'partial-xml'])
def test_focused_results_require_finished_log_and_complete_xml(tmp_path, status):
    root, output, workspace = completed(tmp_path)
    folder = root / 'acp-a4-work'
    folder.mkdir()
    focused = folder / 'focused-v1'
    focused.mkdir()
    selected = receipt(focused)
    (folder / 'focused-v1.xml').write_text('<testsuite tests="2"><testcase/></testsuite>' if status == 'partial-xml'
        else '<testsuite tests="1"><testcase/></testsuite>', encoding='utf-8')
    (folder / 'focused-v1.log').write_text('== 1 passed in 1s ==\n' if status != 'active' else 'collected 1 item\n', encoding='utf-8')
    reports = retention.prune_finished_focus_runs(root, folder)
    assert len(reports) == (1 if status == 'finished' else 0)
    assert selected.exists() is (status != 'finished')


@pytest.mark.parametrize('mode', ['previous', 'output'])
def test_actual_cli_keeps_real_files_and_prunes_completed_receipts(tmp_path, mode):
    root, output, workspace = completed(tmp_path)
    selected = receipt(workspace)
    (output / 'summary.json').write_text('{"result":"passed"}', encoding='utf-8')
    script = tmp_path / 'scripts/process_artifact_retention.py'
    script.parent.mkdir()
    script.write_bytes(MODULE.read_bytes())
    command = [sys.executable, str(script)] + (['--output', str(output)] if mode == 'output' else [])
    result = subprocess.run(command, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['regressions']['removed_files'] == 1 if mode == 'output' else report['regressions'][0]['removed_files'] == 1
    assert not selected.exists() and (output / 'pytest.xml').exists()
