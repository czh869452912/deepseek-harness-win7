import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.acp_stdio_oracle import ROOT, input_cases, validate_observations


@pytest.fixture(scope='module')
def sdk_observations(tmp_path_factory):
    node = shutil.which('node')
    if node is None:
        bundled = Path(os.environ['LOCALAPPDATA']) / 'Volta/tools/image/node/22.22.2/node.exe'
        node = str(bundled) if bundled.is_file() else None
    assert node is not None, 'Pinned development SDK observer requires Node'
    directory = tmp_path_factory.mktemp('acp-sdk-wire')
    cases = input_cases()
    inputs, output = directory / 'cases.json', directory / 'sdk.json'
    inputs.write_text(json.dumps(cases), encoding='utf-8')
    result = subprocess.run([node, str(ROOT / 'scripts/oracles/acp_stdio_sdk.mjs'), str(inputs), str(output)],
                            cwd=str(ROOT), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    rows = json.loads(output.read_text(encoding='utf-8'))
    validate_observations(rows, cases)
    return rows, cases


def test_actual_sdk_and_production_wire_observations_match(sdk_observations, tmp_path):
    rows, cases = sdk_observations
    inputs, output = tmp_path / 'cases.json', tmp_path / 'python.json'
    inputs.write_text(json.dumps(cases), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/oracles/acp_stdio_python.py'), str(inputs), str(output)],
                            cwd=str(ROOT), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    observed = json.loads(output.read_text(encoding='utf-8'))
    validate_observations(observed, cases)
    assert json.dumps(rows, sort_keys=True) == json.dumps(observed, sort_keys=True)


@pytest.mark.parametrize('damage', ['empty', 'missing', 'duplicate', 'reorder', 'extra', 'batch', 'cancel', 'tail', 'outgoing', 'schema'])
def test_missing_or_corrupted_raw_observation_cannot_certify_parity(sdk_observations, damage):
    original, cases = sdk_observations
    rows = copy.deepcopy(original)
    if damage == 'empty':
        rows.clear()
    elif damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = rows[-2]
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'extra':
        rows[0]['normalized'] = True
    elif damage == 'batch':
        rows[2]['output'] = []
    elif damage == 'cancel':
        rows[4]['wrongTypeAborted'] = True
    elif damage == 'tail':
        rows[7]['messages'] = []
    elif damage == 'outgoing':
        rows[14]['settledBeforeReply'] = True
    else:
        rows[-1] = {'mode': rows[-1]['mode']}
    with pytest.raises(ValueError):
        validate_observations(rows, cases)
