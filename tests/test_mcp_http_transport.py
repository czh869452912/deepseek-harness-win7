import asyncio
import json
from pathlib import Path
import sys

import pytest

from dsh.core.abort import AbortController
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.mcp.client import McpClientPlugin
from dsh.mcp.http_client import StreamableHTTPError
from dsh.mcp.protocol import McpError
from dsh.mcp.transport import StreamableHttpMcpTransport


ROOT = Path(__file__).resolve().parents[1]


async def launch(mode, tmp_path):
    output = tmp_path / 'http.json'
    process = await asyncio.create_subprocess_exec(sys.executable,
        str(ROOT / 'scripts/oracles/mcp_http_peer.py'), mode, str(output),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    url = (await asyncio.wait_for(process.stdout.readline(), 5)).decode('utf-8').strip()
    return process, output, StreamableHttpMcpTransport(url, {'Authorization': 'controlled-local'})


async def dispose(process, client):
    await client.close()
    assert not client._pending and not client._writers and not client._tasks
    process.stdin.close()
    await asyncio.wait_for(process.wait(), 5)
    assert process.returncode == 0 and not await process.stderr.read()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['json', 'json-batch', 'json-bom', 'post-sse', 'sse-bom', 'get-sse', 'session', 'delete-405'])
async def test_actual_http_json_sse_and_explicit_session_termination(mode, tmp_path):
    process, output, client = await launch(mode, tmp_path)
    notifications = []
    client.on_notification = notifications.append
    try:
        await client.connect()
        assert (await client.list_tools())['tools'][0]['name'] == 'echo'
        assert (await client.call_tool('echo', {'text': '中文 controlled'}))['content'][0]['text'] == '中文 controlled'
        for index in range(100):
            if Path(str(output) + '.get').exists():
                break
            await asyncio.sleep(0.001)
        if mode == 'get-sse':
            assert notifications == [{'method': 'notifications/tools/list_changed'}]
        if mode in ('session', 'delete-405'):
            assert client.session_id == 'controlled-session'
            await client.terminate_session()
            assert client.session_id is None
    finally:
        await dispose(process, client)
    rows = json.loads(output.read_text(encoding='utf-8'))
    assert all(row['headers']['authorization'] == 'controlled-local' for row in rows)
    assert rows[0]['packet']['method'] == 'initialize' and 'mcp-protocol-version' not in rows[0]['headers']
    assert all(row['headers'].get('mcp-protocol-version') == '2025-11-25' for row in rows[1:])
    assert any(row['method'] == 'DELETE' for row in rows) is (mode in ('session', 'delete-405'))


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['status-401', 'unexpected-content', 'missing-content', 'peer-error'])
async def test_actual_http_failure_cannot_invent_success(mode, tmp_path):
    process, output, client = await launch(mode, tmp_path)
    try:
        await client.connect()
        with pytest.raises(McpError if mode == 'peer-error' else StreamableHTTPError) as failure:
            await client.call_tool('echo', {'text': 'failure'})
        assert failure.value.code == {'peer-error': -32602, 'status-401': 401,
            'unexpected-content': -1, 'missing-content': -1}[mode]
    finally:
        await dispose(process, client)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['cancel', 'timeout', 'close-pending'])
async def test_actual_http_pending_cancel_timeout_and_close_reclaim_resources(mode, tmp_path):
    process, output, client = await launch(mode, tmp_path)
    controller = AbortController()
    try:
        await client.connect()
        pending = asyncio.create_task(client.request({'method': 'tools/call', 'params': {
            'name': 'echo', 'arguments': {'text': 'owned'}}}, signal=controller.signal,
            timeout=100 if mode == 'timeout' else 60000))
        for index in range(100):
            if Path(str(output) + '.call').exists():
                break
            await asyncio.sleep(0.001)
        if mode == 'cancel':
            controller.abort('controlled cancellation')
        elif mode == 'close-pending':
            await client.close()
        with pytest.raises(McpError):
            await pending
    finally:
        await dispose(process, client)


@pytest.mark.asyncio
async def test_actual_http_plugin_activation_tools_consumer_and_scope_unload(tmp_path):
    process, output, unused_client = await launch('session', tmp_path)
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service('tools', tools)
    plugin = McpClientPlugin({'transport': 'streamable-http', 'serverName': 'http-owned',
        'url': unused_client.url, 'headers': {'Authorization': 'controlled-local'},
        'failOnStartupError': True, 'reconnect': {'enabled': False}})
    client = unused_client
    try:
        await unused_client.close()
        fiber = ctx.plugin(plugin)
        await fiber
        client = plugin.connection.client
        assert 'actual consumer' in await tools.execute_tool('mcp__http-owned__echo', {'text': 'actual consumer'})
        await fiber.dispose()
        assert not tools.has_tool('mcp__http-owned__echo')
    finally:
        await ctx.fiber.dispose()
        await dispose(process, client)
