"""Historical capability compatibility and parser controls, not current parity.

Original rc.1 Source facts and inputs retain their byte identities. The Native
legacy-contract providers execute afresh; current Messages/Session contracts
are qualified independently by the rc022 paired lane.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import rc1_capabilities_oracle as oracle
from evidence_fixtures import read_member
from release_gate_fixtures import ARCHIVE, native_fixture


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
    source = read_member(ARCHIVE, 'rc1-capabilities.zip!/source.json')
    inputs = read_member(ARCHIVE, 'rc1-capabilities.zip!/inputs.json')
    assert source['pin'] == oracle.PIN
    assert source['inputSha256'] == 'bfd03a3941712985d1a47d1eece32b7c564919173de4eb8e9b0faef1d30aca2f'
    output = tmp_path_factory.mktemp('historical-capabilities')
    workspace = output / 'workspace'
    for directory in ('src', 'lib', 'dist', '.git', '.venv', '..source', 'space dir'):
        (workspace / directory).mkdir(parents=True)
    for filename in ('src/中文 name.py', 'src/alpha.py', 'src/f😀p.py', 'src/fxxp.py',
                     'lib/alpha.py', 'dist/alpha.py', '.git/a', '.venv/a', '.hidden.py',
                     'file😀.py', '..source/inside.py', 'space dir/a.txt'):
        (workspace / filename).write_text('PRIVATE_BODY_NOT_A_CANDIDATE', encoding='utf-8')
    original_workspace = inputs['workspace']
    inputs['workspace'] = str(workspace)
    input_path = output / 'derived-inputs.json'
    input_path.write_text(json.dumps(inputs, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
    native = native_fixture('capabilities', script='../rc1_capabilities_oracle.py',
                            arguments=('--runtime', '--inputs', input_path))
    assert set(source['observations']) == oracle.REQUIRED
    oracle.validate_runtime(native, ROOT, oracle.digest(source['observations']),
                            hashlib.sha256(input_path.read_bytes()).hexdigest())
    destination = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
    if destination:
        retained = Path(destination) / 'historical-capability-model.json'
        retained.write_text(json.dumps(dict(scope=__doc__, source_pin=source['pin'],
            original_input_sha256=source['inputSha256'], original_workspace=original_workspace,
            derived_workspace=str(workspace), derived_input_sha256=native['inputSha256'],
            source_observations_changed=False), indent=2), encoding='utf-8')
    return source, native


def test_historical_capability_compatibility_keeps_all_original_categories(paired):
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
