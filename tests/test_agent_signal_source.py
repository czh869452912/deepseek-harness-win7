import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

from scripts.oracles.agent_signal_python import observations


ROOT = Path(__file__).resolve().parents[1]


def test_actual_original_model_tool_signal_generation_and_cancelled_admission_recover(tmp_path):
    node = shutil.which('node')
    assert node
    output = tmp_path / 'source.json'
    completed = subprocess.run([node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.agent-signal-probe.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, AGENT_SIGNAL_OUTPUT=str(output)), capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stdout.decode('utf-8', 'replace') + completed.stderr.decode('utf-8', 'replace')
    native = asyncio.run(observations())
    (tmp_path / 'native.json').write_text(json.dumps(native, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    assert canonical(json.loads(output.read_text(encoding='utf-8'))) == canonical(native)
