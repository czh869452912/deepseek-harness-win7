import json
import os
from pathlib import Path
import shutil
import subprocess

from dsh.mcp.config import CONFIG
from dsh.mcp.connection import RECONNECT_ABSENT, resolve_reconnect_policy


ROOT = Path(__file__).resolve().parents[1]


def test_actual_source_configuration_defaults_errors_and_raw_reconnect_resolution(tmp_path):
    node = shutil.which('node')
    assert node, 'source configuration observer requires Node'
    output = tmp_path / 'config.json'
    environment = dict(os.environ, MCP_CONFIG_OUTPUT=str(output))
    subprocess.run([node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.mcp-config-probe.config.mts')],
        cwd=str(ROOT), env=environment, check=True, capture_output=True, timeout=60)
    rows = json.loads(output.read_text(encoding='utf-8'))
    assert len(rows) == 176
    for row in rows:
        try:
            value = CONFIG(row['input']) if row['kind'] == 'config' else resolve_reconnect_policy(row.get('input', RECONNECT_ABSENT), 'controlled')
            result = {'data': value}
        except Exception as error:
            result = {'message': str(error)}
            if row['kind'] == 'config':
                result['name'] = getattr(error, 'name', type(error).__name__)
        assert result == row['result'], row
