"""Explicit checkpoint port of a resolved JS Promise await."""
import asyncio
import importlib.util
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('cordis_boundary_adapter', ROOT / 'scripts/oracles/cordis_boundaries.py')
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
def test_explicit_checkpoint_matches_upstream_resolved_promise():
    report = json.loads((ROOT / 'migration/evidence/artifacts/CORDIS-ASYNC-BOUNDARY-20260927.json').read_text(encoding='utf-8'))
    expected = next(row['upstream']['observation'] for row in report['cases'] if row['case'] == 'C59')
    assert asyncio.run(ADAPTER.scenario(59)) == expected
