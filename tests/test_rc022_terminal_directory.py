"""Current Session directory at launch; persistent shells retain their own state."""
import asyncio
import sys
from types import SimpleNamespace as NS

import pytest

from dsh.sandbox.sandbox_policy import SandboxPolicyService
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.terminal.authorized import AuthorizedLocalTerminalPlugin, AuthorizedPersistentPwshPlugin
from dsh.terminal.service import TerminalSessionService
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_providers_launch_reuse_and_unload(tmp_path):
    from scripts.rc022_terminal_directory_probe import observe
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert [rows[name]['cwd'] for name in ('initial', 'changed', 'explicit')] == ['<work>', '<work>/moved', '<work>']
    assert rows['persistent-first']['value'] == rows['persistent-reused']['value'] == '<work>/moved'
    assert rows['persistent-reused']['current'] == '<work>'
    assert rows['persistent-reused']['allocations'] == 1
    assert rows['persistent-unload'] == dict(name='persistent-unload', closed=True, retained=0)
    assert rows['persistent-recreated']['value'] == '<work>'
    assert rows['persistent-recreated']['allocations'] == 2
    assert rows['owner-unload']['closed']


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='native WinPTY/PowerShell consumer')
async def test_actual_winpty_keeps_directory_and_reset_starts_at_latest_session_directory(tmp_path):
    (tmp_path/'moved').mkdir()
    fixture = await setup(tmp_path/'fixture', directory=tmp_path)
    ctx = fixture.ctx
    await ctx.plugin(SandboxPolicyService, dict(mode='danger-full-access', workspaceRoot=str(tmp_path)))
    runtime = LocalSubprocessRuntime(ctx)
    await ctx.plugin(TerminalSessionService)
    await ctx.plugin(AuthorizedLocalTerminalPlugin, dict(shellDialect='pwsh', idleSilenceMs=250,
                                                       pollIntervalMs=10, timeoutMs=10000))
    fiber = await ctx.plugin(AuthorizedPersistentPwshPlugin, dict(timeoutMs=10000))
    handle = await ctx.agents.create(dict(sessionId='native-directory', meta=dict(cwd=str(tmp_path)),
                                         agentOptions=dict(provider='script', model='model')))
    agent = handle.agent
    async def run(command):
        return await asyncio.wait_for(ctx.tools.get('pwsh').execute(dict(command=command),
                                      NS(agent=agent, signal=fixture.signal)), 15)
    async def assert_directory(expected):
        # A PTY wraps long paths at its configured width. Compare inside the
        # real shell and emit a short observation, preserving the exact path.
        quoted = str(expected).replace("'", "''")
        assert await run("Write-Output ('CWD=' + ((Get-Location).Path -eq '" + quoted + "'))") == 'CWD=True'
    try:
        await ctx.workingDirectory.set(agent, 'moved', fixture.signal)
        await assert_directory(tmp_path/'moved')
        await run('$directoryState = 42')
        await ctx.workingDirectory.set(agent, '..', fixture.signal)
        await assert_directory(tmp_path/'moved')
        assert await run('Write-Output $directoryState') == '42'
        await fiber.plugin.reset(agent, 'directory-test reset')
        await assert_directory(tmp_path)
        assert await run("Write-Output ('STATE=' + $directoryState)") == 'STATE='
        await handle.dispose()
        assert not runtime.terminals and not ctx.terminals.list(agent)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_directory_resolution_never_allocates_terminal(tmp_path):
    fixture = await setup(tmp_path/'fixture', directory=tmp_path)
    ctx = fixture.ctx
    async def forbidden(*args):
        pytest.fail('a terminal was allocated after directory resolution failed')
    async def unavailable(*args):
        raise RuntimeError('cwd unavailable')
    ctx.workingDirectory.ensure = unavailable
    ctx.set_service('terminals', NS(spawn=forbidden, list=lambda _:[]))
    fiber = await ctx.plugin(AuthorizedPersistentPwshPlugin)
    handle = await ctx.agents.create(dict(sessionId='failure', meta=dict(cwd=str(tmp_path)),
                                         agentOptions=dict(provider='script', model='model')))
    try:
        with pytest.raises(RuntimeError, match='cwd unavailable'):
            await ctx.tools.get('pwsh').execute(dict(command='pwd'), NS(agent=handle.agent, signal=fixture.signal))
        assert not fiber.plugin.live and not fiber.plugin.running
    finally:
        await ctx.fiber.dispose()
