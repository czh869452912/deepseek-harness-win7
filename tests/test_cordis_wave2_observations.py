"""Replay Python against frozen observations from the pinned upstream runtime."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cordis_wave2_adapter", str(ROOT / "scripts/oracles/cordis_python.py")
)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
REPORT = json.loads((ROOT / "migration/evidence/artifacts/CORDIS-WAVE2-BEFORE.json").read_text(encoding="utf-8"))
EXPECTED = {row["case"]: row["upstream"]["observation"] for row in REPORT["cases"]}


@pytest.mark.parametrize("case", range(22, 31))
def test_python_matches_frozen_upstream_observation(case):
    assert asyncio.run(ADAPTER.scenario(case)) == EXPECTED["C%d" % case]
