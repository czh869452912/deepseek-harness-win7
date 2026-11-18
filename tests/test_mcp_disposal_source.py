import json
from pathlib import Path
import subprocess
import sys
from historical_tool_cache_models import tool_cache_pair


ROOT = Path(__file__).resolve().parents[1]


def test_historical_mcp_disposal_native_queue_and_factory_ownership(tmp_path):
    output = tmp_path / 'paired.json'
    report, _, _ = tool_cache_pair('mcp-disposal', output)
    assert report['status'] == 'passed' and report['cases'] == 7
