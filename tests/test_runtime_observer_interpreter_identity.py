import copy
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

from scripts import runtime_context_oracle, javascript_ready_oracle, javascript_workflow_oracle
from test_current_release_gate import context_runtime_fixture, ready_runtime_fixture, javascript_runtime_fixture


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('consumer', ['context', 'ready', 'workflow'])
@pytest.mark.parametrize('mode', ['selected', 'extracted'])
def test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes(consumer, mode):
    fixture, oracle = {'context': (context_runtime_fixture, runtime_context_oracle),
        'ready': (ready_runtime_fixture, javascript_ready_oracle),
        'workflow': (javascript_runtime_fixture, javascript_workflow_oracle)}[consumer]
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
        extra = [] if consumer == 'context' else [runtime['assets']]
        with pytest.raises(ValueError, match='selected interpreter'):
            oracle.validate_runtime(runtime, root, oracle.observation_digest(runtime['observations']),
                runtime['modules'], *extra, check_files=mode == 'selected')
