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
async def test_retained_sdk_factory_failure_keeps_close_barrier_without_retry(tmp_path):
    output = tmp_path / 'factory.json'
    # The archived disposal probe closes during disposal; this consumer reaches
    # the supervisor's failed-generation close barrier before calling dispose.
    # Keep that distinct retained-provider unit contract explicit.
    expected = dict(
        outcome=dict(name='TypeError', message='Invalid URL', code='ERR_INVALID_URL'),
        logs=[['warn', 'mcp-client(controlled): connection attempt failed: TypeError: Invalid URL'],
              ['error', 'mcp-client(controlled): failed generation did not close within 5000ms — reconnect stopped to avoid overlapping server processes; reload the plugin or restart the Host to retry']])
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
        observed = {'outcome': {'name': error.name, 'message': str(error), 'code': error.code}, 'logs': logs}
        output.write_text(json.dumps(observed, indent=2), encoding='utf-8')
        assert observed == expected
        assert handle.client is None and handle._retry_task is None
    finally:
        await handle.dispose()
