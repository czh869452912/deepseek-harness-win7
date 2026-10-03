import asyncio
import json
from pathlib import Path
import sys

import pytest

from dsh.acp.mcp import AcpMcpConfigError
from dsh.core.abort import AbortController
from dsh.core.tools import ToolExecutionInput
from dsh.mcp.client import McpClientPlugin
from test_acp_session_controls import boot_profile, stop_profile
from test_mcp_http_transport import launch, dispose
from test_mcp_stdio_transport import SERVER, server


def declarations(server_path, name='fixture'):
    return [{'name': name, 'command': sys.executable, 'args': [str(server_path)],
             'env': [{'name': 'EXPLICIT_TOKEN', 'value': 'session-owned'}]}]


def clients(ctx):
    return [fiber.plugin.connection.client for fiber in ctx.registry.list_fibers()
            if isinstance(fiber.plugin, McpClientPlugin) and fiber.plugin.connection is not None
            and fiber.plugin.connection.client is not None]


async def echo(ctx, agent, text):
    return await ctx.get('tools').execute(ToolExecutionInput('owned-echo', 'mcp__fixture__echo',
        {'text': text}, agent=agent, signal=AbortController().signal))


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['jsonl', 'sqlite'])
async def test_actual_profile_session_mcp_tools_are_isolated_reaped_and_remounted(tmp_path, backend, monkeypatch, server):
    runtime, bridge, unused = await boot_profile(tmp_path, backend, monkeypatch)
    ctx = runtime['ctx']
    owned = []
    try:
        params = {'cwd': str(tmp_path), 'mcpServers': declarations(server)}
        first = await bridge.new_session(ctx, params)
        first_agent = bridge.sessions[first['sessionId']].agent
        owned.extend(clients(ctx))
        assert len(owned) == 1 and owned[0].proc.returncode is None
        assert not ctx.get('tools').list_tools()
        assert [tool.name for tool in ctx.get('tools').list_tools(first_agent)] == ['mcp__fixture__echo']
        result = await echo(ctx, first_agent, 'first owned')
        assert not result.is_error and result.value['structuredContent']['explicit'] == 'session-owned'
        assert result.value['content'] == [{'type': 'text', 'text': 'first owned'}]
        second = await bridge.new_session(ctx, params)
        second_agent = bridge.sessions[second['sessionId']].agent
        second_client = next(client for client in clients(ctx) if client is not owned[0])
        owned.append(second_client)
        await bridge.close_session(ctx, first)
        assert owned[0].proc.returncode == 0 and not owned[0]._pending
        assert second_client.proc.returncode is None
        assert not (await echo(ctx, second_agent, 'sibling remains')).is_error
        await bridge.resume_session(ctx, dict(first, **params))
        remounted = next(client for client in clients(ctx) if client not in owned)
        owned.append(remounted)
        assert remounted.proc.pid != owned[0].proc.pid and remounted.proc.returncode is None
        assert not (await echo(ctx, bridge.sessions[first['sessionId']].agent, 'fresh resume')).is_error
        await bridge.close_session(ctx, first)
        await bridge.resume_session(ctx, dict(first, cwd=str(tmp_path), mcpServers=[]))
        assert not ctx.get('tools').list_tools(bridge.sessions[first['sessionId']].agent)
        await bridge.close_session(ctx, first)
        await bridge.close_session(ctx, second)
        assert not ctx.get('tools').list_tools() and not ctx.get('agents').list()
    finally:
        await stop_profile(runtime)
    assert all(client.proc.returncode == 0 and not client._pending for client in owned)


@pytest.mark.asyncio
async def test_actual_profile_http_mcp_headers_and_tool_consumer_are_session_owned(tmp_path, monkeypatch):
    process, output, unused_client = await launch('session', tmp_path)
    runtime, bridge, unused = await boot_profile(tmp_path, 'jsonl', monkeypatch)
    ctx = runtime['ctx']
    client = unused_client
    try:
        initialized = await bridge.initialize(ctx, {})
        assert initialized['agentCapabilities']['mcpCapabilities'] == {'http': True}
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path), 'mcpServers': [{
            'type': 'http', 'name': 'fixture', 'url': unused_client.url,
            'headers': [{'name': 'Authorization', 'value': 'session-owned'}]}]})
        client = clients(ctx)[0]
        agent = bridge.sessions[created['sessionId']].agent
        result = await echo(ctx, agent, 'real HTTP consumer')
        assert not result.is_error and result.value['content'] == [{'type': 'text', 'text': 'real HTTP consumer'}]
        assert not ctx.get('tools').list_tools()
        await bridge.close_session(ctx, created)
        assert not client._pending and not client._writers and not client._tasks
    finally:
        await stop_profile(runtime)
        await unused_client.close()
        await dispose(process, client)
    rows = json.loads(output.read_text(encoding='utf-8'))
    assert all(row['headers']['authorization'] == 'session-owned' for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['invalid-declaration', 'missing-executable'])
async def test_actual_factory_rolls_back_all_mcp_children_before_agent_publication(tmp_path, monkeypatch, server, failure):
    runtime, bridge, unused = await boot_profile(tmp_path, 'jsonl', monkeypatch)
    ctx, processes = runtime['ctx'], []
    original_spawn = asyncio.create_subprocess_exec
    async def spawn(*arguments, **options):
        process = await original_spawn(*arguments, **options)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    try:
        servers = declarations(server)
        servers.append({'name': 'broken', 'command': 'relative' if failure == 'invalid-declaration'
                        else str(tmp_path / 'missing.exe'), 'args': [], 'env': []})
        with pytest.raises(AcpMcpConfigError if failure == 'invalid-declaration' else RuntimeError):
            await bridge.new_session(ctx, {'cwd': str(tmp_path), 'mcpServers': servers})
        assert len(processes) == (0 if failure == 'invalid-declaration' else 1)
        assert all(process.returncode == 0 for process in processes)
        assert not ctx.get('agents').list() and not ctx.get('sessions').list()
        assert not bridge.sessions and not ctx.get('tools').list_tools()
        assert await ctx.get('sessionPersistence').list() == []
    finally:
        await stop_profile(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize('stop', ['request-abort', 'bridge-close'])
async def test_cancelled_unpublished_mcp_setup_drains_real_child(tmp_path, monkeypatch, stop):
    marker = tmp_path / 'initializing'
    release = tmp_path / 'release'
    server_path = tmp_path / 'blocked.py'
    controlled = SERVER.replace('import json,os,sys', 'import json,os,sys,pathlib,time').replace(
        '    if method=="initialize":', '    if method=="initialize":\n'
        '        pathlib.Path(sys.argv[1]).write_text("ready",encoding="utf-8")\n'
        '        while not pathlib.Path(sys.argv[2]).exists():\n'
        '            time.sleep(0.01)')
    server_path.write_text(controlled, encoding='utf-8')
    runtime, bridge, unused = await boot_profile(tmp_path, 'jsonl', monkeypatch)
    ctx, processes = runtime['ctx'], []
    original_spawn = asyncio.create_subprocess_exec
    async def spawn(*arguments, **options):
        process = await original_spawn(*arguments, **options)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    controller = AbortController()
    pending = asyncio.create_task(bridge.new_session(ctx, {'cwd': str(tmp_path), 'mcpServers': [{
        'name': 'blocked', 'command': sys.executable, 'args': [str(server_path), str(marker), str(release)], 'env': []}]}, controller.signal))
    try:
        async def admitted():
            while not marker.exists():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(admitted(), 5)
        assert len(processes) == 1 and not ctx.get('agents').list() and not bridge.sessions
        if stop == 'request-abort':
            controller.abort(RuntimeError('controlled setup abort'))
        else:
            await bridge.close(ctx)
        assert not ctx.get('agents').list() and not bridge.sessions
        release.write_text('release', encoding='utf-8')
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(pending, 10)
        assert processes[0].returncode == 0
        assert not ctx.get('agents').list() and not ctx.get('sessions').list()
        assert not ctx.get('tools').list_tools() and not bridge.sessions
        assert await ctx.get('sessionPersistence').list() == []
    finally:
        release.write_text('release', encoding='utf-8')
        await stop_profile(runtime)
        await asyncio.gather(pending, return_exceptions=True)
