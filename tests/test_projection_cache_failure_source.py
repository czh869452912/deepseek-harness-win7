import json
from pathlib import Path
import subprocess
import sys
import pytest

from scripts.projection_cache_failure_oracle import validate_observations, validate_runtime
from historical_tool_cache_models import tool_cache_pair


def test_historical_original_and_retained_native_cache_failures(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'cache.json'
    report, source, native = tool_cache_pair('projection-cache-failure', output)
    assert report['status'] == 'passed'
    assert report['cases'] == 9
    validate_observations(source)
    validate_runtime(native)
    assert source == native['observations']


@pytest.mark.asyncio
async def test_current_v4_cache_cold_failure_identity_and_prepared_fallback(tmp_path):
    from scripts.oracles.projection_cache_failure_python import observe
    rows = {row['name']: row['observed'] for row in await observe(tmp_path / 'current', 4)}
    assert len(rows) == 9
    assert all(row['document']['record']['identity']['formatVersion'] == 4 for row in rows.values())
    assert rows['cold-malformed']['error'] == dict(
        name='TypeError', message='controlled invalid cache value', sameParserFailure=True)
    assert rows['cold-matching']['snapshot']['values'] == {'controlled/count': 8}
    assert rows['cold-matching']['applied'] == [1]
    for name, row in rows.items():
        if name not in ('cold-malformed', 'cold-matching'):
            assert row['snapshot']['values'] == {'controlled/count': 2}
            assert row['applied'] == [0, 1]
