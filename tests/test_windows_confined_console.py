import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.scope import scope_of
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.sandbox.local import LocalSandboxProvider
from dsh.sandbox.sandbox_policy import SandboxPolicyService, set_sandbox_mode
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.terminal.local import LocalTerminalBackend, LocalTerminalPlugin, DEFAULTS
from dsh.terminal.persistent_pwsh import PersistentPwshPlugin
from dsh.terminal.service import TerminalSessionService


pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Physical Windows confined console')


class UnusedModel:
    provider, model = 'unused', 'unused'


@asynccontextmanager
async def confined(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ctx = Context()
    owner = other = None
    try:
        ctx.set_service('llm', UnusedModel())
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(AgentLoopPlugin)
        owner = await ctx.get('agent_loop').create('console-owner', meta=dict(cwd=str(workspace)))
        other = await ctx.get('agents').create('console-sibling', meta=dict(cwd=str(workspace)))
        await ctx.plugin(SandboxPolicyService, dict(mode='workspace-write', workspaceRoot=str(workspace)))
        await ctx.plugin(LocalSandboxProvider)
        runtime = LocalSubprocessRuntime(ctx)
        await ctx.plugin(TerminalSessionService)
        await ctx.plugin(LocalTerminalPlugin, dict(shellDialect='pwsh', idleSilenceMs=150,
            pollIntervalMs=10, timeoutMs=5000))
        fiber = await ctx.plugin(PersistentPwshPlugin, dict(timeoutMs=6000))
        tool = ctx.get('tools').get('pwsh', scope_of(owner.agent.ctx))

        async def execute(command, agent=None, signal=None):
            return await asyncio.wait_for(tool.execute(dict(command=command),
                SimpleNamespace(agent=agent or owner.agent, signal=signal or AbortController().signal)), 12)

        yield SimpleNamespace(ctx=ctx, owner=owner, other=other, runtime=runtime, fiber=fiber,
            execute=execute, workspace=workspace, terminals=ctx.get('terminals'))
    finally:
        try:
            if other is not None:
                await other.dispose()
        finally:
            try:
                if owner is not None:
                    await owner.dispose()
            finally:
                await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_confined_console_retains_state_unicode_and_actual_write_boundary(tmp_path):
    async with confined(tmp_path) as state:
        assert await state.execute("$retained_value = 1436; Write-Output 'INITIAL_READY'") == 'INITIAL_READY'
        assert await state.execute("Write-Output ('VALUE=' + $retained_value); Write-Output ('中' + '文')") == 'VALUE=1436\n中文'
        assert await state.execute("Set-Content -LiteralPath 'allowed.txt' -Value 'OWNED_WRITE'; Write-Output 'WROTE'") == 'WROTE'
        assert (state.workspace / 'allowed.txt').read_bytes().strip() == b'OWNED_WRITE'
        forbidden = tmp_path / 'forbidden.txt'
        refusal = await state.execute("Set-Content -LiteralPath '" + str(forbidden) + "' -Value 'DENIED'")
        assert not forbidden.exists() and 'UnauthorizedAccessException' in refusal
        assert await state.execute("Write-Output ('VALUE=' + $retained_value)", state.other.agent) == 'VALUE='
        with pytest.raises(RuntimeError, match='cannot change sandbox mode'):
            set_sandbox_mode(state.owner.agent.session, 'read-only')
        await state.fiber.dispose()
        assert not state.runtime.terminals
        assert state.ctx.get('tools').get('pwsh', scope_of(state.owner.agent.ctx)) is None


@pytest.mark.asyncio
async def test_confined_console_timeout_and_cancel_close_owned_jobs(tmp_path):
    async with confined(tmp_path) as state:
        assert await state.execute("$retained_value = 1436; Write-Output 'INITIAL_READY'") == 'INITIAL_READY'
        state.fiber.plugin.config['timeoutMs'] = 800
        result = await state.execute("Write-Output ('PARTIAL' + '_RETAINED'); Start-Sleep -Seconds 30")
        assert 'timed out' in result and 'PARTIAL_RETAINED' in result and 'shell was reset' in result
        state.fiber.plugin.config['timeoutMs'] = 6000
        assert await state.execute("Write-Output ('VALUE=' + $retained_value)") == 'VALUE='
        controller = AbortController()
        pending = asyncio.create_task(state.execute('Start-Sleep -Seconds 30', signal=controller.signal))
        await asyncio.sleep(.3)
        controller.abort(RuntimeError('owned-console-cancel'))
        with pytest.raises(RuntimeError, match='^owned-console-cancel$'):
            await pending
        assert not state.terminals.list(state.owner.agent)
        await state.fiber.dispose()
        assert not state.runtime.terminals


def test_confined_pipe_runner_has_no_console_and_retains_captured_stdio(tmp_path):
    workspace = tmp_path / 'workspace'
    temp = tmp_path / 'temp'
    workspace.mkdir()
    temp.mkdir()
    runner = Path(__file__).resolve().parents[1] / 'dsh/sandbox/windows_runner.py'
    command = "import ctypes;print('PIPE_READY');print(bool(ctypes.windll.kernel32.GetConsoleWindow()))"
    completed = subprocess.run([sys.executable, str(runner), '--workspace', str(workspace),
        '--temp', str(temp), '--mode', 'workspace-write', '--', sys.executable, '-c', command],
        cwd=str(workspace), stdin=subprocess.DEVNULL, capture_output=True, timeout=12)
    assert completed.returncode == 0 and completed.stdout == b'PIPE_READY\r\nFalse\r\n'
    assert not completed.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize('observation', ['own-output-line', 'input-echo', 'prefixed-token', 'exited-before-ready'])
async def test_startup_nonce_requires_its_own_live_output_line(monkeypatch, observation):
    import dsh.terminal.local as local

    class Session:
        def __init__(self, terminal, config):
            self.command = None
            self.closed = False
            self.sends = 0

        def startSend(self, request):
            self.command = request['text'] or self.command
            self.sends += 1
            done = asyncio.get_running_loop().create_future()
            done.set_result(dict(waitReason='session_exit' if observation == 'exited-before-ready'
                else 'timeout' if self.sends > 1 else 'idle'))
            return SimpleNamespace(done=done)

        def read(self, request=None):
            marker = re.search(r'__DSH_READY_[0-9a-f]+__', self.command).group(0)
            text = '\n' + marker + '\n' if observation == 'own-output-line' else (
                self.command + '\n' if observation == 'input-echo' else 'prefix' + marker + '\n')
            return dict(text=text)

        async def close(self, reason):
            self.closed = True

    sessions = []

    def session(terminal, config):
        selected = Session(terminal, config)
        sessions.append(selected)
        return selected

    class Runtime:
        async def spawn_terminal(self, spec):
            return object()

    policy = SimpleNamespace(resolve=lambda request: dict(mode='danger-full-access', workspaceRoot=os.getcwd()))
    services = dict(sandboxPolicy=policy, subprocess=Runtime())
    ctx = SimpleNamespace(get=services.get)
    backend = LocalTerminalBackend(ctx, dict(DEFAULTS, shellDialect='pwsh', shellPath='powershell.exe', shellArgs=[]))
    monkeypatch.setattr(local, 'LocalTerminalSession', session)
    monkeypatch.setattr(backend, 'fence', lambda owner: None)
    spec = dict(owner=SimpleNamespace(id='owner', session=object()), sessionId='nonce-control')
    if observation == 'own-output-line':
        assert await backend.spawn(spec) is sessions[0]
        assert not sessions[0].closed
    else:
        with pytest.raises(RuntimeError, match='failed to reach startup readiness'):
            await backend.spawn(spec)
        assert sessions[0].closed
