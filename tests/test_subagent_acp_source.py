import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from dsh.subagent.acp import CONFIG, SubagentAcp
from scripts.oracles.subagent_acp_python import native_observations, public_observation


ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))




def test_actual_original_acp_subagent_runs_match_native_complete_public_observations(tmp_path, monkeypatch):
    monkeypatch.setenv('AMBIENT_SECRET', 'private-parent-secret')
    node = shutil.which('node')
    assert node
    output = tmp_path / 'source.json'
    completed = subprocess.run([node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.subagent-acp-probe.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, SUBAGENT_ACP_WORKSPACE=str(tmp_path), SUBAGENT_ACP_PYTHON=sys.executable,
                 SUBAGENT_ACP_PEER=str(ROOT / 'scripts/oracles/subagent_acp_peer.py'), SUBAGENT_ACP_OUTPUT=str(output)),
        capture_output=True, timeout=90)
    assert completed.returncode == 0, completed.stdout.decode('utf-8', 'replace') + completed.stderr.decode('utf-8', 'replace')
    original = json.loads(output.read_text(encoding='utf-8'))
    assert len(original['rows']) == 22
    assert len({row['name'] for row in original['rows']}) == 22
    assert len(original['configurations']) == 6
    for row in original['configurations']:
        captured = []
        registry = SimpleNamespace(registerProvider=captured.append)
        context = SimpleNamespace(get=lambda name: registry)
        observation = {'input': row['input']}
        try:
            config = CONFIG(row['input'])
            SubagentAcp(context, config).apply(context)
            backend = captured[0]
            observation['result'] = {'config': config, 'name': backend.name,
                'capabilities': backend.capabilities, 'inheritsParentContext': backend.inheritsParentContext}
        except Exception as error:
            observation['error'] = {'name': getattr(error, 'name', 'Error'), 'message': str(error)}
        assert canonical(observation) == canonical(row)
    async def observe_all():
        results = []
        for row in original['rows']:
            results.append({'name': row['name'], 'observations': await native_observations(tmp_path, row)})
        return results
    native = asyncio.run(observe_all())
    (tmp_path / 'native.json').write_text(json.dumps(native, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    for row, observed in zip(original['rows'], native):
        assert row['name'] == observed['name']
        assert canonical(public_observation(row['observations'])) == canonical(public_observation(observed['observations'])), row['name']
