import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.oracles.subagent_acp_teardown_python import observations, public_observation


ROOT = Path(__file__).resolve().parents[1]


def test_actual_original_subprocess_acp_teardown_failure_aggregate_causes_and_identity(tmp_path):
    source = tmp_path / 'source.json'
    completed = subprocess.run([shutil.which('node'), '--expose-internals',
        str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config',
        str(ROOT / 'scripts/oracles/vitest.subagent-acp-teardown-probe.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, SUBAGENT_ACP_TEARDOWN_WORKSPACE=str(tmp_path), SUBAGENT_ACP_TEARDOWN_OUTPUT=str(source),
            SUBAGENT_ACP_PYTHON=sys.executable, SUBAGENT_ACP_PEER=str(ROOT / 'scripts/oracles/subagent_acp_peer.py')),
        capture_output=True, timeout=90)
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode('utf-8', 'replace')
    original = json.loads(source.read_text(encoding='utf-8'))
    native = asyncio.run(observations(tmp_path))
    (tmp_path / 'native.json').write_text(json.dumps(native, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)
    assert len(original) == len(native) == 4
    for source_row, native_row in zip(original, native):
        assert canonical(public_observation(source_row)) == canonical(public_observation(native_row)), source_row['name']
