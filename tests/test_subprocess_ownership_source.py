import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

from scripts.oracles.subprocess_ownership_python import observations


ROOT = Path(__file__).resolve().parents[1]


def test_actual_original_subprocess_service_pending_exit_and_teardown_failure_ownership(tmp_path):
    source = tmp_path / 'source.json'
    completed = subprocess.run([shutil.which('node'), '--expose-internals',
        str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config',
        str(ROOT / 'scripts/oracles/vitest.subprocess-ownership-probe.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, SUBPROCESS_OWNERSHIP_OUTPUT=str(source)), capture_output=True, timeout=90)
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode('utf-8', 'replace')
    original = json.loads(source.read_text(encoding='utf-8'))
    native = asyncio.run(observations())
    (tmp_path / 'native.json').write_text(json.dumps(native, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)
    assert len(original) == len(native) == 4
    assert canonical(original) == canonical(native)
