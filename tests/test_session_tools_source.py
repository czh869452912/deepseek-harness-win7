import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import session_tools_oracle as oracle


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    output = tmp_path_factory.mktemp('session-tools-paired') / 'result.json'
    result = subprocess.run([sys.executable, str(oracle.ROOT / 'scripts/session_tools_oracle.py'), '--output', str(output)],
                            capture_output=True, timeout=150, env=os.environ.copy())
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    return (json.loads(output.read_text(encoding='utf-8')), json.loads(output.with_name('result.source.json').read_text(encoding='utf-8')),
            json.loads(output.with_name('result.native.json').read_text(encoding='utf-8')))


def test_actual_optional_session_tools_source_native_pair(paired):
    report, source, native = paired
    assert report['status'] == 'passed' and report['cases'] == 78
    oracle.validate_runtime(native, oracle.ROOT, oracle.source_identity(source))


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'runtime', 'hash', 'inventory', 'value', 'digest'])
def test_damaged_session_tool_receipts_are_refused(paired, damage):
    _, source, original = paired
    report = copy.deepcopy(original)
    digest = oracle.source_identity(source)
    if damage == 'missing':
        report = None
    elif damage == 'root':
        report['root'] = str(Path(report['root']) / 'foreign')
    elif damage == 'module':
        report['moduleFile'] = 'foreign'
    elif damage == 'runtime':
        report['python'] = '3.9.0'
    elif damage == 'hash':
        report['modules'][oracle.MODULES[0]] = '0' * 64
    elif damage == 'inventory':
        report['rows'].pop()
    elif damage == 'value':
        report['rows'][0]['value'] = 'foreign'
    else:
        digest = '0' * 64
    with pytest.raises(ValueError):
        oracle.validate_runtime(report, oracle.ROOT, digest)
