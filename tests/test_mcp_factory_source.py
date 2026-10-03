import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dsh.mcp.connection import McpConnection


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_actual_sdk_factory_failure_stops_at_the_close_barrier_without_retry(tmp_path):
    output = tmp_path / 'factory.json'
    source_run = subprocess.run([shutil.which('node'), '--expose-internals',
        str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config',
        str(ROOT / 'scripts/oracles/vitest.mcp-factory-probe.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, MCP_FACTORY_OUTPUT=str(output)), capture_output=True, timeout=30)
    output.with_suffix('.source.log').write_bytes(source_run.stdout + source_run.stderr)
    assert source_run.returncode == 0
    expected = json.loads(output.read_text(encoding='utf-8'))
    logs = []
    class Context:
        logger = SimpleNamespace(**{level: lambda message, level=level: logs.append([level, message])
            for level in ('warn', 'error', 'info')})
        def get(self, name):
            return None
    handle = McpConnection(Context(), {'transport': 'streamable-http', 'serverName': 'controlled',
        'url': 'invalid', 'headers': {}}, {'enabled': True, 'initialDelayMs': 1, 'maxDelayMs': 1000, 'maxAttempts': 1})
    try:
        error = (await handle.ready)['error']
        assert {'outcome': {'name': error.name, 'message': str(error), 'code': error.code}, 'logs': logs} == expected
        assert handle.client is None and handle._retry_task is None
    finally:
        await handle.dispose()
