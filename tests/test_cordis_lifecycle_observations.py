"""Lifecycle and handle scenarios frozen from the pinned upstream."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'cordis_lifecycle_adapter', str(ROOT / 'scripts/oracles/cordis_include.py')
)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
REPORT = json.loads((ROOT / 'migration/evidence/artifacts/CORDIS-C1-C47-20260927.json').read_text(encoding='utf-8'))
EXPECTED = {row['case']: row['upstream']['observation'] for row in REPORT['cases']}
RESTART = json.loads((ROOT / 'migration/evidence/artifacts/CORDIS-RESTART-20260927.json').read_text(encoding='utf-8'))
EXPECTED.update({row['case']: row['upstream']['observation'] for row in RESTART['cases']})


@pytest.mark.parametrize('case', [40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51])
def test_matched_lifecycle_observation(case):
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(case), timeout=10))
    assert actual == EXPECTED['C%d' % case]


def test_refresh_disposal_observation_waits_for_settlement(monkeypatch):
    """A loaded loop must not release the refresh before observing disposal."""
    from dsh.cordis.fiber import Fiber

    settle = Fiber._await_quiescent

    async def delayed_settlement(self):
        await asyncio.sleep(0.08)
        await settle(self)

    monkeypatch.setattr(Fiber, '_await_quiescent', delayed_settlement)
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(42), timeout=10))
    assert actual == EXPECTED['C42']
