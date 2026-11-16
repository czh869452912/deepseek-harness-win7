import asyncio
import json
import os
import sys

import pytest

from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.typert.artifact import read_generated_artifact
from scripts.rc022_candidate_fixture import setup
from test_rc022_manager_wire import http, WireClient, SOURCE


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='Actual Windows WinPTY carrier')
async def test_loader_browser_terminal_actual_duplex_input_screen_and_unload(tmp_path):
    command = os.path.join(os.environ['SystemRoot'], 'System32', 'cmd.exe')
    extra = [('subprocess-local', {}), ('sandbox-policy', dict(mode='workspace-write', workspaceRoot=str(tmp_path))),
        ('typert-registry', {}), ('api-remote-access', {}), ('api-gateway', dict(websocketCompression='none')),
        ('api-remotes', {}), ('credentials-local', dict(path=str(tmp_path/'credentials.yaml'))), ('client-connection', {}),
        ('api-terminal-controller', dict(shell=dict(path=command, name='Command Prompt', args=['/q']))),
        ('host-webserver', dict(host='127.0.0.1', port=0))]
    def prepare(ctx):
        ctx.inject(['typert'], lambda child: child.effect(lambda: child.typert.register(read_generated_artifact(SOURCE/'packages/api/terminal-controller/lib/typert.host.js'))))
    ctx = await setup(tmp_path, extra=extra, prepare=prepare)
    lease = client = None; runtime = ctx.subprocess; screens = ctx.terminalScreens; javascript = ctx.jsRuntime
    async def rpc(method, args):
        response = await http(ctx.webServer, '/api/terminal/'+method, dict(type='client-request', rpcId=method, method='terminal/'+method, payload=dict(args=args)), cookie)
        assert response['status'] == 200, response
        result = json.loads(response['body'])['result']
        assert 'error' not in result, result
        return result.get('value')
    try:
        lease = await ctx.agents.create(dict(sessionId='owner', agentOptions=dict(provider='script', model='m')))
        response = await http(ctx.webServer, '/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        assert response['status'] == 302, response
        cookie = response['headers']['set-cookie'].split(';')[0]
        environment = await rpc('environment', dict(agentId='owner'))
        assert os.path.normcase(environment['cwd']) == os.path.normcase(str(tmp_path))
        created = await rpc('create', dict(agentId='owner', request=dict(id='owned', cols=80, rows=24)))
        assert created['state'] == 'running' and created['origin'] == 'user'
        client = await WireClient().connect(ctx.webServer.listened_port, cookie=cookie)
        await client.send(dict(type='open', streamId='terminal', endpoint='terminal/attach', payload=dict(args=dict(agentId='owner', id='owned'))))
        frames = [await client.receive()]
        assert frames[0].get('value', {}).get('type') == 'snapshot' and frames[0]['value']['writable'], frames
        await client.send(dict(type='item', streamId='terminal', value=dict(type='write', sequence=1, data='echo candidate-terminal-marker\r', typed=True)))
        while not (any(frame.get('value', {}).get('type') == 'ack' for frame in frames) and 'candidate-terminal-marker' in json.dumps(frames)):
            frames.append(await client.receive())
        terminal = ctx.terminalController.terminal(lease.agent, 'owned')
        page = terminal.readScreen(dict(offset=0, count=100, maxBytes=16000))
        assert 'candidate-terminal-marker' in page['text'], page
        renamed = await rpc('rename', dict(agentId='owner', id='owned', title='Renamed terminal'))
        roster = await rpc('list', dict(sessionId='owner'))
        assert roster[0]['title'] == 'Renamed terminal'
        await rpc('close', dict(agentId='owner', id='owned'))
        await client.send(dict(type='cancel', streamId='terminal'))
        await client.close(); client = None
        entry = next(entry for entry in ctx.loader.entries() if entry.options.get('id') == 'api-terminal-controller')
        await await_callback_result(ctx.loader.update(entry.id, dict(disabled=True)))
        assert not runtime.live and not screens.engines and not javascript._workers
        (tmp_path/'terminal-wire-observations.json').write_text(json.dumps(dict(environment=environment, created=created, frames=frames, page=page, roster=roster, renamed=renamed), indent=2), encoding='utf-8')
    finally:
        if client is not None: await client.close()
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
    assert not runtime.live and not screens.engines and not javascript._workers


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='Actual persistent PowerShell WinPTY carrier')
async def test_loader_persistent_shell_tool_keeps_state_and_unloads_owner(tmp_path):
    extra = [('subprocess-local', {}), ('sandbox-policy', dict(mode='danger-full-access', workspaceRoot=str(tmp_path))),
        ('terminal', {}), ('terminal-bash', dict(shellDialect='pwsh', idleSilenceMs=250, pollIntervalMs=10, timeoutMs=10000)),
        ('tool-pwsh-persistent', dict(timeoutMs=10000))]
    ctx = await setup(tmp_path, extra=extra); lease = None; runtime = ctx.subprocess; terminals = ctx.terminals
    async def run(identity, command):
        result = await asyncio.wait_for(ctx.tools.execute(ToolExecutionInput(identity, 'pwsh', dict(command=command), agent=lease.agent, signal=NEVER_ABORTED)), 15)
        assert not result.is_error, (result.error, result.content)
        return result.value
    try:
        lease = await ctx.agents.create(dict(sessionId='persistent-owner', agentOptions=dict(provider='script', model='m')))
        first = await run('set', "$candidateState = 42; Write-Output 'FIRST'")
        second = await run('read', "Write-Output ('STATE=' + $candidateState)")
        assert first == 'FIRST' and second == 'STATE=42'
        assert len(terminals.sessions) == 1
        entry = next(entry for entry in ctx.loader.entries() if entry.options.get('id') == 'tool-pwsh-persistent')
        await await_callback_result(ctx.loader.update(entry.id, dict(disabled=True)))
        assert not terminals.sessions and not runtime.live
        (tmp_path/'persistent-wire-observations.json').write_text(json.dumps(dict(first=first, second=second, remainingSessions=len(terminals.sessions)), indent=2), encoding='utf-8')
    finally:
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
    assert not terminals.sessions and not runtime.live
