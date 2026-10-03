import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('acp_model_output_oracle', ROOT / 'scripts/acp_model_output_oracle.py')
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


@pytest.fixture(scope='module')
def observations(tmp_path_factory):
    output = tmp_path_factory.mktemp('acp-model-observations') / 'observed.json'
    subprocess.run([sys.executable, str(ROOT / 'scripts/oracles/acp_model_output_python.py'), str(output)],
                   cwd=str(ROOT), check=True, capture_output=True, timeout=20)
    return json.loads(output.read_text(encoding='utf-8'))


def test_declared_runtime_observations_are_complete(observations):
    ORACLE.validate_observations(observations)


@pytest.mark.parametrize('index', range(8))
def test_matching_but_incomplete_mode_cannot_pass(observations, index):
    rows = copy.deepcopy(observations)
    rows[index].pop(next(iter(ORACLE.FIELDS[rows[index]['mode']])))
    with pytest.raises((ValueError, KeyError, TypeError)):
        ORACLE.validate_observations(rows)


@pytest.mark.parametrize('damage', ['empty', 'duplicate', 'reorder', 'bool-usage', 'lost-default',
                                  'no-serialization', 'wrong-pin', 'lost-raw-input', 'wrong-output-order'])
def test_vacuous_or_corrupted_observations_are_rejected(observations, damage):
    rows = copy.deepcopy(observations)
    if damage == 'empty':
        rows.clear()
    elif damage == 'duplicate':
        rows[-1] = rows[0]
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'bool-usage':
        rows[-1]['assistant'][-1]['used'] = True
    elif damage == 'lost-default':
        rows[1]['snapshot']['reasoningEffort'] = 'high'
    elif damage == 'no-serialization':
        rows[5]['blocked'] = False
    elif damage == 'wrong-pin':
        rows[6]['wrongTurn'] = rows[6]['released']
    elif damage == 'lost-raw-input':
        rows[-1]['calls'][1]['rawInput'] = None
    else:
        rows[-1]['assistant'].reverse()
    with pytest.raises((ValueError, KeyError, TypeError)):
        ORACLE.validate_observations(rows)
