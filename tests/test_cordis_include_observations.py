"""Include transactions replayed against frozen pinned-upstream observations."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'cordis_include_adapter', str(ROOT / 'scripts/oracles/cordis_include.py')
)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
REPORT = json.loads((ROOT / 'migration/evidence/artifacts/CORDIS-INCLUDE-BEFORE-20260927.json').read_text(encoding='utf-8'))
EXPECTED = {row['case']: row['upstream']['observation'] for row in REPORT['cases']}


@pytest.mark.parametrize('case', range(37, 40))
def test_include_matches_frozen_upstream_observation(case):
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(case), timeout=10))
    assert actual == EXPECTED['C%d' % case]
