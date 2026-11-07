"""Retained capability observer must exercise the current provider closure."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import rc1_capabilities_oracle as oracle


ROOT = Path(__file__).resolve().parents[1]


def test_source_freeze_reads_tracked_and_compiled_bytes_on_every_pass(tmp_path):
    values = {'package.json': b'{}', 'src/plugin.ts': b'first',
              'lib/plugin.js': b'built', 'lib/nested/data.json': b'{}',
              '.dsh-build/client-build-environment.json': b'{}',
              'lib/node_modules/ignored.js': b'external', 'untracked.txt': b'external'}
    for name, data in values.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'package.json', 'src/plugin.ts'], check=True, capture_output=True)
    expected = {name: hashlib.sha256(values[name]).hexdigest() for name in (
        '.dsh-build/client-build-environment.json', 'lib/nested/data.json', 'lib/plugin.js', 'package.json', 'src/plugin.ts')}
    observed = oracle.source_inputs(tmp_path)
    assert observed == expected and list(observed) == sorted(expected)
    path = tmp_path / 'lib/plugin.js'
    metadata = path.stat()
    path.write_bytes(b'other')
    os.utime(str(path), ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    changed = oracle.source_inputs(tmp_path)
    assert changed != observed and changed['lib/plugin.js'] == hashlib.sha256(b'other').hexdigest()
    (tmp_path / 'src/plugin.ts').unlink()
    with pytest.raises(FileNotFoundError):
        oracle.source_inputs(tmp_path)


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    output = tmp_path_factory.mktemp('current-capabilities') / 'pair'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/rc1_capabilities_oracle.py'),
        '--output', str(output)], capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    source = json.loads((output / 'source.json').read_text(encoding='utf-8'))
    native = json.loads((output / 'native.json').read_text(encoding='utf-8'))
    assert set(source['observations']) == oracle.REQUIRED
    oracle.validate_runtime(native, ROOT, oracle.digest(source['observations']), native['inputSha256'])
    return source, native


def test_actual_current_capabilities_keep_all_original_categories(paired):
    source, native = paired
    assert source['observations'] == native['observations']
    assert len(native['observations']['chunkDecode']) == 9
    assert [len(row[0]['texts']) for row in native['observations']['chunkPack']] == [2, 3, 1025, 3]
    assert native['observations']['projectionLineage']['initial']['val']['cut'] == 2


@pytest.mark.parametrize('module', sorted(oracle.CURRENT_MODULES))
def test_capability_observer_rejects_missing_current_provider(paired, module):
    source, original = paired
    native = copy.deepcopy(original)
    del native['modules'][module]
    with pytest.raises(ValueError):
        oracle.validate_runtime(native, ROOT, oracle.digest(source['observations']), native['inputSha256'])


@pytest.mark.parametrize('category', sorted(oracle.REQUIRED))
def test_capability_observer_rejects_missing_current_category(paired, category):
    source, original = paired
    native = copy.deepcopy(original)
    del native['observations'][category]
    native['sourceObservationsSha256'] = oracle.digest(native['observations'])
    with pytest.raises(ValueError):
        oracle.validate_runtime(native, ROOT, oracle.digest(source['observations']), native['inputSha256'])
