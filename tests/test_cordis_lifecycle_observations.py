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


@pytest.mark.parametrize('case', [40, 41, 42, 43, 44, 45, 46, 47])
def test_matched_lifecycle_observation(case):
    actual = asyncio.run(asyncio.wait_for(ADAPTER.scenario(case), timeout=10))
    assert actual == EXPECTED['C%d' % case]
