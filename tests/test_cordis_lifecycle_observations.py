"""Include and Fiber lifecycle observations of the current pinned upstream."""
import asyncio
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'cordis_lifecycle_adapter', str(ROOT / 'scripts/oracles/cordis_include.py')
)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
REPORT = json.loads((ROOT / 'tests/fixtures/rc022-include-lifecycle-source.json').read_text(encoding='utf-8'))
EXPECTED = REPORT['observations']


def test_current_include_observation_inputs_are_pinned():
    assert REPORT['source_commit'] == '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    assert REPORT['node'] == 'v24.9.0'
    assert set(EXPECTED) == {str(case) for case in range(40, 52)}
    for path, digest in REPORT['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


@pytest.mark.parametrize('case', [40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51])
def test_matched_lifecycle_observation(case):
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(case), timeout=10))
    assert actual == EXPECTED[str(case)]


def test_refresh_disposal_joins_inflight_refresh(monkeypatch):
    """Slow teardown must still join its in-flight refresh after release."""
    from dsh.cordis.fiber import Fiber

    settle = Fiber._await_quiescent

    async def delayed_settlement(self):
        await asyncio.sleep(0.08)
        await settle(self)

    monkeypatch.setattr(Fiber, '_await_quiescent', delayed_settlement)
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(42), timeout=10))
    assert actual == EXPECTED['42']
