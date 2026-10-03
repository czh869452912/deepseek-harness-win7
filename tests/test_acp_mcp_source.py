import json
import os
from pathlib import Path
import shutil
import subprocess

from dsh.acp.mcp import resolve_mcp_configs


ROOT = Path(__file__).resolve().parents[1]


def test_actual_acp_source_mcp_declarations_defaults_errors_and_prevalidation(tmp_path):
    node = shutil.which('node')
    assert node, 'ACP source observer requires Node'
    output = tmp_path / 'acp-mcp.json'
    completed = subprocess.run([node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.acp-mcp-probe.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, ACP_MCP_OUTPUT=str(output)), capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stdout.decode('utf-8', 'replace') + completed.stderr.decode('utf-8', 'replace')
    rows = json.loads(output.read_text(encoding='utf-8'))
    assert len(rows) == 58
    for row in rows:
        try:
            result = {'data': resolve_mcp_configs(row['servers'], row['cwd'])}
        except Exception as error:
            result = {'name': getattr(error, 'name', type(error).__name__), 'message': str(error), 'mounted': []}
        assert result == row['result'], row
