import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_acp_mcp_runtime import declarations, echo
from test_acp_session_controls import boot_profile, stop_profile
from test_mcp_stdio_transport import server


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_actual_source_and_native_acp_session_mcp_consumer_lifecycle(tmp_path, monkeypatch, server):
    node = shutil.which('node')
    assert node, 'ACP source lifecycle observer requires Node'
    output = tmp_path / 'source.json'
    completed = subprocess.run([node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.acp-mcp-runtime.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, ACP_MCP_RUNTIME_OUTPUT=str(output), ACP_MCP_PEER=str(server), ACP_MCP_PYTHON=sys.executable),
        capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stdout.decode('utf-8', 'replace') + completed.stderr.decode('utf-8', 'replace')
    expected = json.loads(output.read_text(encoding='utf-8'))
    runtime, bridge, unused = await boot_profile(tmp_path, 'jsonl', monkeypatch)
    ctx, observed = runtime['ctx'], {}
    def names(agent=None):
        return [tool.name for tool in ctx.get('tools').list_tools(agent)]
    async def result(created, text):
        value = await echo(ctx, bridge.sessions[created['sessionId']].agent, text)
        return {'value': value.value, 'content': value.content, 'isError': value.is_error}
    try:
        observed['mcpCapabilities'] = (await bridge.initialize(ctx, {}))['agentCapabilities']['mcpCapabilities']
        params = {'cwd': str(tmp_path), 'mcpServers': declarations(server)}
        first = await bridge.new_session(ctx, params)
        observed['globalTools'] = names()
        observed['firstTools'] = names(bridge.sessions[first['sessionId']].agent)
        observed['firstResult'] = await result(first, 'first owned')
        second = await bridge.new_session(ctx, params)
        await bridge.close_session(ctx, first)
        observed['siblingResult'] = await result(second, 'sibling remains')
        await bridge.resume_session(ctx, dict(first, **params))
        observed['resumedResult'] = await result(first, 'fresh resume')
        await bridge.close_session(ctx, first)
        await bridge.resume_session(ctx, dict(first, cwd=str(tmp_path), mcpServers=[]))
        observed['emptyResumeTools'] = names(bridge.sessions[first['sessionId']].agent)
        await bridge.close_session(ctx, first)
        await bridge.close_session(ctx, second)
        observed['finalTools'] = names()
        observed['finalAgents'] = len(ctx.get('agents').list())
        assert observed == expected
    finally:
        await stop_profile(runtime)
