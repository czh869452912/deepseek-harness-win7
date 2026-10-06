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

    def observe_run(command, name, selected_output, env=None, timeout=None):
        selected = Path(next(argument.split('=', 1)[1] for argument in command if argument.startswith('--basetemp=')))
        selected.relative_to(gate.ROOT / '.goose/out')
        assert selected.name.startswith('g-')
        assert selected.parent == gate.ROOT / '.goose/out'
        assert command[1:4] == ['-m', 'pytest', 'tests']
        assert timeout == 2800 and name == 'pytest' and selected_output == output
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
        original_run(command, name, selected_output, **arguments)

    monkeypatch.setattr(gate, 'run', selected_consumer)
    gate.run_python_regression(sys.executable, output, dict(os.environ))
    assert commands[0][3] == 'tests'
    log = (output / 'pytest.log').read_text(encoding='utf-8')
    assert '1 passed' in log and '$GIT_DIR' not in log
    retained = output / 'pytest-workspace'
    assert list(retained.glob('test_split_tasks*/.goose/runs/project/worktrees/*-split-*/a.py'))
    mapping = json.loads((output / 'pytest-workspace-mapping.json').read_text(encoding='utf-8'))
    assert not Path(mapping['execution_path']).exists()
    assert Path(mapping['retained_path']) == retained
    if os.name == 'nt':
        assert max(len(str(path)) for path in retained.rglob('*') if path.is_file()) > 260


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
