import copy
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

from scripts import runtime_context_oracle, javascript_ready_oracle, javascript_workflow_oracle, persistence_read_oracle
from scripts import javascript_initial_oracle, session_number_oracle
from scripts import session_diagnostic_oracle
from scripts import session_restore_sign_oracle
from scripts import runtime_full_request_oracle, deepseek_error_oracle, deepseek_capture_oracle
from test_current_release_gate import context_runtime_fixture, ready_runtime_fixture, javascript_runtime_fixture, read_runtime_fixture
from test_current_release_gate import initial_runtime_fixture, number_runtime_fixture
from test_current_release_gate import diagnostic_runtime_fixture
from test_current_release_gate import restore_sign_runtime_fixture
from test_current_release_gate import full_request_runtime_fixture, deepseek_error_runtime_fixture, deepseek_capture_runtime_fixture


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('consumer', ['context', 'ready', 'workflow', 'read', 'initial', 'number', 'diagnostic', 'restore-sign', 'full-request', 'deepseek-error', 'deepseek-capture'])
@pytest.mark.parametrize('mode', ['selected', 'extracted'])
def test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes(consumer, mode):
    fixture, oracle = {'context': (context_runtime_fixture, runtime_context_oracle),
        'ready': (ready_runtime_fixture, javascript_ready_oracle),
        'workflow': (javascript_runtime_fixture, javascript_workflow_oracle),
        'read': (read_runtime_fixture, persistence_read_oracle),
        'initial': (initial_runtime_fixture, javascript_initial_oracle),
        'number': (number_runtime_fixture, session_number_oracle),
        'diagnostic': (diagnostic_runtime_fixture, session_diagnostic_oracle),
        'restore-sign': (restore_sign_runtime_fixture, session_restore_sign_oracle),
        'full-request': (full_request_runtime_fixture, runtime_full_request_oracle),
        'deepseek-error': (deepseek_error_runtime_fixture, deepseek_error_oracle),
        'deepseek-capture': (deepseek_capture_runtime_fixture, deepseek_capture_oracle)}[consumer]
    runtime = copy.deepcopy(fixture())
    with tempfile.TemporaryDirectory(prefix='unselected-interpreter-', dir=str(ROOT / '.goose/out')) as directory:
        foreign = Path(directory) / 'python.exe'
        shutil.copyfile(sys.executable, str(foreign))
        root = ROOT if mode == 'selected' else Path(directory)
        if mode == 'extracted':
            rogue = root / 'nested'
            rogue.mkdir()
            shutil.copyfile(str(foreign), str(rogue / 'python.exe'))
            foreign = rogue / 'python.exe'
            runtime['root'] = str(root)
        runtime['executable'] = str(foreign)
        extra = [] if consumer in ('context', 'number', 'diagnostic', 'restore-sign', 'full-request', 'deepseek-error', 'deepseek-capture') else [runtime['assets']]
        with pytest.raises(ValueError, match='selected interpreter'):
            oracle.validate_runtime(runtime, root, oracle.observation_digest(runtime['rows' if consumer in ('read', 'number', 'diagnostic', 'restore-sign', 'deepseek-error', 'deepseek-capture') else 'observations']),
                runtime['modules'], *extra, check_files=mode == 'selected')
