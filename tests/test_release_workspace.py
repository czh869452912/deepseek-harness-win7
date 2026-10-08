import json
import os
from pathlib import Path
import sys

import pytest

from scripts import verify_release as gate


@pytest.mark.parametrize('outcome', ['passed', 'failed'])
def test_short_pytest_workspace_retains_owned_success_and_failure_artifacts(tmp_path, monkeypatch, outcome):
    output = tmp_path / ('descriptive-release-' + 'a' * 70)
    output.mkdir()
    executions = []

    def observe_run(command, name, selected_output, env=None, timeout=None, accepted=None):
        selected = Path(next(argument.split('=', 1)[1] for argument in command if argument.startswith('--basetemp=')))
        selected.relative_to(gate.ROOT / '.goose/out')
        assert selected.name.startswith('g-')
        assert selected.parent == gate.ROOT / '.goose/out'
        assert command[1:4] == ['-m', 'pytest', 'tests']
        assert timeout == 3600 and name == 'pytest' and selected_output == output
        assert accepted == (0, 1)
        executions.append(selected)
        (selected / 'owned-observation.json').write_text('{"result":"retained"}\n', encoding='utf-8')
        if outcome == 'failed':
            raise RuntimeError('fixture rejected')

    monkeypatch.setattr(gate, 'run', observe_run)
    if outcome == 'failed':
        with pytest.raises(RuntimeError, match='fixture rejected'):
            gate.run_python_regression(sys.executable, output, {})
    else:
        gate.run_python_regression(sys.executable, output, {})
    assert len(executions) == 1 and not executions[0].exists()
    mapping = json.loads((output / 'pytest-workspace-mapping.json').read_text(encoding='utf-8'))
    assert mapping['execution_path'] == str(executions[0])
    assert Path(mapping['retained_path']) == output / 'pytest-workspace'
    assert json.loads((output / 'pytest-workspace/owned-observation.json').read_text(encoding='utf-8')) == dict(result='retained')
    with pytest.raises(RuntimeError, match='Fresh retained pytest workspace'):
        gate.run_python_regression(sys.executable, output, {})
    assert len(executions) == 1


def test_short_pytest_workspace_runs_actual_shared_checkpoint_git_consumer(tmp_path, monkeypatch):
    output = tmp_path / ('descriptive-release-' + 'b' * 70)
    output.mkdir()
    original_run = gate.run
    commands = []

    def selected_consumer(command, name, selected_output, **arguments):
        commands.append(command)
        command = list(command)
        command[3] = 'tests/test_goose_project.py::test_split_tasks_fork_shared_checkpoint_without_losing_progress'
        return original_run(command, name, selected_output, **arguments)

    monkeypatch.setattr(gate, 'run', selected_consumer)
    gate.run_python_regression(sys.executable, output, dict(os.environ))
    assert commands[0][3] == 'tests'
    log = (output / 'pytest.log').read_text(encoding='utf-8')
    assert '1 passed' in log and '$GIT_DIR' not in log
    retained = output / 'pytest-workspace'
    physical_retained = Path(gate.regression_retention_path(retained))
    observations = list(physical_retained.glob('test_split_tasks*/.goose/runs/project/worktrees/*-split-*/a.py'))
    assert observations and all(path.read_text(encoding='utf-8') == 'value = 8\n' for path in observations)
    mapping = json.loads((output / 'pytest-workspace-mapping.json').read_text(encoding='utf-8'))
    assert not Path(mapping['execution_path']).exists()
    assert Path(mapping['retained_path']) == retained
    if os.name == 'nt':
        assert max(len(str(path)) for path in physical_retained.rglob('*') if path.is_file()) > 260


@pytest.mark.parametrize('outcome', ['passed', 'failed'])
def test_retention_error_never_hides_primary_regression_failure(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    output = tmp_path / '.goose/out/candidate'
    output.mkdir(parents=True)

    def execute(command, name, selected_output, **arguments):
        if outcome == 'failed':
            raise RuntimeError('primary regression failure')

    def refuse_move(source, destination):
        raise PermissionError('retention directory locked')

    monkeypatch.setattr(gate, 'run', execute)
    monkeypatch.setattr(gate.os, 'rename', refuse_move)
    error_type = RuntimeError if outcome == 'failed' else PermissionError
    message = 'primary regression failure' if outcome == 'failed' else 'retention directory locked'
    with pytest.raises(error_type, match=message):
        gate.run_python_regression(sys.executable, output, {})
    failure = json.loads((output / 'pytest-retention-failure.json').read_text(encoding='utf-8'))
    assert failure['name'] == 'PermissionError' and failure['message'] == 'retention directory locked'
    mapping = json.loads((output / 'pytest-workspace-mapping.json').read_text(encoding='utf-8'))
    assert Path(mapping['execution_path']).is_dir()
    assert not Path(mapping['retained_path']).exists()


@pytest.mark.parametrize('status', [0, 7])
def test_actual_release_process_preserves_exit_status_and_logs(tmp_path, status):
    script = "import sys; print('actual retained subprocess output', flush=True); sys.exit(" + str(status) + ')'
    command = [sys.executable, '-c', script]
    if status:
        with pytest.raises(RuntimeError, match=r'owned-process failed \(7\)'):
            gate.run(command, 'owned-process', tmp_path, timeout=10)
    else:
        assert gate.run(command, 'owned-process', tmp_path, timeout=10) == 0
    assert 'actual retained subprocess output' in (tmp_path / 'owned-process.log').read_text(encoding='utf-8')
    assert not (tmp_path / 'owned-process-cleanup.json').exists()


@pytest.mark.parametrize('failure', ['retention', 'cleanup-audit'])
def test_normal_failed_pytest_status_survives_secondary_housekeeping_failure(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    output = tmp_path / '.goose/out/release'
    output.mkdir(parents=True)
    monkeypatch.setattr(gate, 'run', lambda *arguments, **keywords: 1)
    if failure == 'retention':
        def refuse_move(source, target):
            raise PermissionError('retained folder locked')
        monkeypatch.setattr(gate.os, 'rename', refuse_move)
    else:
        def refuse_cleanup(*arguments):
            raise PermissionError('cleanup locked')
        original_write = Path.write_text
        def refuse_audit(path, *arguments, **keywords):
            if path.name == 'pytest-artifact-cleanup-failure.json':
                raise OSError('diagnostic disk write failed')
            return original_write(path, *arguments, **keywords)
        monkeypatch.setattr(gate, 'prune_completed_regression', refuse_cleanup)
        monkeypatch.setattr(Path, 'write_text', refuse_audit)
    with pytest.raises(RuntimeError, match=r'pytest failed \(1\)'):
        gate.run_python_regression(sys.executable, output, {})


@pytest.mark.parametrize('outcome', ['passed', 'failed'])
def test_actual_release_pytest_exits_before_owned_artifact_cleanup(tmp_path, monkeypatch, outcome):
    child = tmp_path / 'child'
    scripts = child / 'scripts'
    tests = child / 'tests'
    scripts.mkdir(parents=True)
    tests.mkdir()
    (scripts / '__init__.py').write_text('', encoding='utf-8')
    (scripts / 'process_artifact_retention.py').write_bytes((gate.ROOT / 'scripts/process_artifact_retention.py').read_bytes())
    (tests / 'conftest.py').write_bytes((gate.ROOT / 'tests/conftest.py').read_bytes())
    (tests / 'test_process.py').write_text(
        "def test_process(tmp_path):\n"
        "    import os\n"
        "    assert os.environ['DSH_RELEASE_PYTEST_OUTPUT']\n"
        "    (tmp_path / 'portable.zip').write_bytes(b'exact candidate archive')\n"
        "    (tmp_path / 'receipt.json').write_text('{\"runtime\":{\"checks\":[\"actual runtime\"]}}', encoding='utf-8')\n"
        "    (tmp_path / 'actual-source.json').write_text('{\"source\":\"retained\"}', encoding='utf-8')\n"
        + ("    assert False, 'retained child failure'\n" if outcome == 'failed' else ''), encoding='utf-8')
    output = child / '.goose/out/release'
    output.mkdir(parents=True)
    monkeypatch.setattr(gate, 'ROOT', child)
    environment = dict(os.environ)
    environment['DSH_RELEASE_PYTEST_OUTPUT'] = 'inherited owner must be replaced'
    if outcome == 'failed':
        with pytest.raises(RuntimeError, match=r'pytest failed \(1\)'):
            gate.run_python_regression(sys.executable, output, environment)
    else:
        gate.run_python_regression(sys.executable, output, environment)
    assert environment['DSH_RELEASE_PYTEST_OUTPUT'] == 'inherited owner must be replaced'
    retained = output / 'pytest-workspace'
    assert not list(retained.glob('test_process*/receipt.json'))
    assert list(retained.glob('test_process*/actual-source.json'))
    audit = json.loads((output / 'unit-receipts-pruned.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'completed' and audit['removed_files'] == 1
    assert not (retained / 'unit-receipts-pruned.json').exists()
    log = (output / 'pytest.log').read_text(encoding='utf-8')
    assert ('1 passed' if outcome == 'passed' else 'retained child failure') in log
    assert (output / 'pytest.xml').is_file()


def test_actual_timeout_retires_redirector_descendants_before_workspace_move(tmp_path):
    import subprocess

    workspace = tmp_path / 'execution'
    workspace.mkdir()
    ready = tmp_path / 'child-ready.json'
    child_code = (
        'import json,os,time; from pathlib import Path; '
        'os.chdir(' + repr(str(workspace)) + '); '
        'Path(' + repr(str(ready)) + ').write_text(json.dumps(dict(pid=os.getpid())), encoding="utf-8"); '
        'time.sleep(60)'
    )
    parent_code = (
        'import subprocess,sys; '
        'child=subprocess.Popen([sys.executable,"-c",' + repr(child_code) + ']); '
        'child.wait()'
    )
    with pytest.raises(subprocess.TimeoutExpired):
        gate.run([sys.executable, '-c', parent_code], 'owned-timeout', tmp_path, timeout=5)
    assert ready.is_file(), 'actual descendant did not enter its owned execution directory'
    child_pid = json.loads(ready.read_text(encoding='utf-8'))['pid']
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.OpenProcess(0x100000, False, child_pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 5000) == 0
            finally:
                kernel.CloseHandle(handle)
    workspace.rename(tmp_path / 'retained')
    cleanup = json.loads((tmp_path / 'owned-timeout-cleanup.json').read_text(encoding='utf-8'))
    assert cleanup['primary_failure'] == 'TimeoutExpired'
    assert cleanup['root_exit_code'] is not None and cleanup.get('cleanup_failure') is None
