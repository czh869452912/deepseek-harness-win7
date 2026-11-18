"""Current Loader consumers; retired HMR API is replaced by rc022 queue tests."""
import asyncio
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'cordis_consumer_adapter', str(ROOT / 'scripts/oracles/cordis_consumers.py')
)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
REPORT = json.loads((ROOT / 'tests/fixtures/rc022-loader-consumers-source.json').read_text(encoding='utf-8'))
EXPECTED = REPORT['observations']


def test_current_loader_consumer_inputs_are_pinned():
    assert REPORT['source_commit'] == '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    assert REPORT['node'] == 'v24.9.0'
    assert set(EXPECTED) == {'31', '32'}
    for path, digest in REPORT['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


# registerConfig/refreshConfig no longer exist on the current Source provider.
# tests/test_rc022_hmr_queue.py covers their watchConfig/runExclusive successors,
# including duplicate paths, serialization, cancellation and disposal ownership.
@pytest.mark.parametrize('case', [31, 32])
def test_consumer_matches_frozen_upstream_observation(case):
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(case), timeout=10))
    assert actual == EXPECTED[str(case)]
