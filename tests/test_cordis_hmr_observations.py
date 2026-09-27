"""Real-file module reload observations captured from the pinned upstream."""
import asyncio
import importlib.util
import json
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('cordis_hmr_adapter', ROOT / 'scripts/oracles/cordis_hmr.py')
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
REPORT = json.loads((ROOT / 'migration/evidence/artifacts/CORDIS-HMR-COMPLEX-20260927.json').read_text(encoding='utf-8'))
EXPECTED = {row['case']:row['upstream']['observation'] for row in REPORT['cases']}
@pytest.mark.parametrize('case', [52, 53, 54, 55, 56, 57, 60, 61])
def test_module_reload_matches_upstream(case):
    adapter = ADAPTER
    if case in (60, 61):
        filename = 'cordis_hmr_complex.py' if case == 60 else 'cordis_hmr_batch.py'
        spec = importlib.util.spec_from_file_location('extra_hmr_adapter', ROOT / 'scripts/oracles' / filename)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
    assert asyncio.run(asyncio.wait_for(adapter.scenario(case), 10)) == EXPECTED['C%d' % case]
