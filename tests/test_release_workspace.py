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
        assert timeout == 2400 and name == 'pytest' and selected_output == output
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
