import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import sqlite_format_oracle as oracle


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    output = tmp_path_factory.mktemp('sqlite-format-paired') / 'result.json'
    result = subprocess.run([sys.executable, str(oracle.ROOT / 'scripts/sqlite_format_oracle.py'), '--output', str(output)],
                            capture_output=True, timeout=150, env=os.environ.copy())
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    return (json.loads(output.read_text(encoding='utf-8')), json.loads(output.with_name('result.source.json').read_text(encoding='utf-8')),
            json.loads(output.with_name('result.native.json').read_text(encoding='utf-8')))


def test_actual_schema19_format_source_native_pair(paired):
    report, source, native = paired
    assert report['status'] == 'passed' and report['cases'] == 826
    oracle.validate_runtime(native, oracle.ROOT, *oracle.source_identity(source))


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'library', 'runtime', 'hash', 'asset', 'inventory',
                                  'value', 'digest', 'frames', 'version'])
def test_damaged_sqlite_format_receipts_are_refused(paired, damage):
    _, source, original = paired
    report = copy.deepcopy(original)
    digest, frames = oracle.source_identity(source)
    if damage == 'missing':
        report = None
    elif damage == 'root':
        report['root'] = str(Path(report['root']) / 'foreign')
    elif damage == 'module':
        report['moduleFile'] = 'foreign'
    elif damage == 'library':
        report['libraryFile'] = 'foreign'
    elif damage == 'runtime':
        report['python'] = '3.9.0'
    elif damage == 'hash':
        report['modules'][oracle.MODULES[0]] = '0' * 64
    elif damage == 'asset':
        report['assets']['zstd-dictionary.bin'] = '0' * 64
    elif damage == 'inventory':
        report['rows'].pop()
    elif damage == 'value':
        report['rows'][0]['value'] = 'foreign'
    elif damage == 'digest':
        digest = '0' * 64
    elif damage == 'frames':
        frames = '0' * 64
    else:
        report['zstdVersion'] = 'foreign'
    with pytest.raises(ValueError):
        oracle.validate_runtime(report, oracle.ROOT, digest, frames)
