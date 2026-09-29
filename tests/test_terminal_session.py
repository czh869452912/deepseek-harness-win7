import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

from dsh.terminal.local import DEFAULTS, LocalTerminalPlugin
from dsh.terminal.service import TerminalSessionService, TerminalError
from dsh.terminal.session import LocalTerminalSession
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.sandbox.sandbox_policy import SandboxPolicyService, set_sandbox_mode
from test_subagent_in_process import setup


@pytest.mark.asyncio
async def test_deadline_does_not_release_unfinished_write_and_decoder_flushes():
    read_fd, write_fd = os.pipe()
    output = os.fdopen(read_fd, 'rb', buffering=0)
    gate = asyncio.Event()
    done = asyncio.get_running_loop().create_future()
    async def write(text):
        await gate.wait()
    async def terminate():
        gate.set()
        os.close(write_fd)
        done.set_result(SimpleNamespace(exitCode=1, signal=None))
    terminal = SimpleNamespace(output=output, pid=1, done=done, write=write, terminate=terminate)
    session = LocalTerminalSession(terminal, dict(DEFAULTS, timeoutMs=30, pollIntervalMs=5))
    try:
        operation = session.startSend(dict(text='blocked', submit=True))
        os.write(write_fd, b'prefix\xe4')
        assert (await operation.done)['waitReason'] == 'timeout'
        with pytest.raises(TerminalError, match='draining write'):
            session.startSend(dict(text='another', submit=True))
        gate.set()
        await session.driver
        await session.close('test')
        assert session.status()['kind'] == 'exited'
        # The session drains decoded output through EOF on natural termination.
        assert 'prefix' in session.read()['text']
    finally:
        await session.close('test')
        output.close()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='native WinPTY console')
async def test_actual_powershell_backend_persists_state_fences_policy_and_disposes(tmp_path):
    ctx, _, owner = await setup()
    await ctx.plugin(SandboxPolicyService, dict(mode='danger-full-access', workspaceRoot=str(tmp_path)))
    runtime = LocalSubprocessRuntime(ctx)
    await ctx.plugin(TerminalSessionService)
    backend = await ctx.plugin(LocalTerminalPlugin, dict(shellDialect='pwsh', idleSilenceMs=500, timeoutMs=10000))
    terminals = ctx.get('terminals')
    try:
        spawned = await asyncio.wait_for(terminals.spawn(owner.agent, dict(type='shell')), 15)
        identity = spawned['sessionId']
        async def command(text):
            result = await terminals.startSend(owner.agent, identity, dict(text=text, submit=True)).done
            assert result['waitReason'] == 'inferred_idle'
            return result['viewport']
        await command('$persisted = 98765')
        out = await command("Write-Output ('VALUE=' + $persisted); Write-Output ('中' + '文')")
        assert 'VALUE=98765' in out and '中文' in out
        with pytest.raises(RuntimeError, match='cannot change sandbox mode'):
            set_sandbox_mode(owner.agent.session, 'read-only')
        assert runtime.terminals
        await owner.dispose()
        assert not runtime.terminals and not terminals.hasOwnerActivity(owner.agent)
    finally:
        await owner.dispose()
        await ctx.fiber.dispose()
