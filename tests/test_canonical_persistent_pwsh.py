import asyncio
import sys
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.core.scope import scope_of
from dsh.sandbox.sandbox_policy import SandboxPolicyService
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.terminal.local import LocalTerminalPlugin
from dsh.terminal.service import TerminalSessionService
from dsh.terminal.persistent_pwsh import PersistentPwshPlugin, capture, wrap_command
from test_subagent_in_process import setup


def test_echo_cannot_fake_nonce_completion_and_ps2_escape():
    wrapper = wrap_command('Write-Output "${x}"\n\x1b', 'START', 'END:')
    assert '`e' not in wrapper and '$([char]27)' in wrapper
    assert capture(wrapper + '\n', 'START', 'END:', wrapper) is None
    assert capture(wrapper + '\nSTART\nhello\nEND:7\n', 'START', 'END:', wrapper) == dict(text='hello', incomplete=False, exitCode=7)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='native WinPTY console')
async def test_registered_tool_state_owner_isolation_timeout_reset_and_unload(tmp_path):
    ctx, _, owner = await setup()
    await ctx.plugin(SandboxPolicyService, dict(mode='danger-full-access', workspaceRoot=str(tmp_path)))
    runtime = LocalSubprocessRuntime(ctx)
    await ctx.plugin(TerminalSessionService)
    await ctx.plugin(LocalTerminalPlugin, dict(shellDialect='pwsh', idleSilenceMs=250, pollIntervalMs=10, timeoutMs=10000))
    fiber = await ctx.plugin(PersistentPwshPlugin, dict(timeoutMs=10000))
    tool = ctx.get('tools').get('pwsh', scope_of(owner.agent.ctx))
    other = await ctx.get('agents').create('other-shell')
    execution = SimpleNamespace(agent=owner.agent, signal=AbortController().signal)
    async def run(text, exec_ctx=execution):
        return await asyncio.wait_for(tool.execute(dict(command=text), exec_ctx), 15)
    try:
        assert await run('$persisted = 4321') == ''
        assert await run("Write-Output ('RESULT=' + $persisted)") == 'RESULT=4321'
        assert await run("Write-Output ('RESULT=' + $persisted)", SimpleNamespace(agent=other.agent, signal=AbortController().signal)) == 'RESULT='
        assert await run("Write-Output ('中' + '文')\nWrite-Output 'next'") == '中文\nnext'
        assert (await run('cmd /c exit 7')).endswith('[exit code: 7]')
        # Timeout the running command, retain its partial output, kill the shell,
        # then prove the next call starts in a fresh process.
        fiber.plugin.config['timeoutMs'] = 700
        timed = await run("Write-Output ('partial' + '-output'); Start-Sleep -Seconds 30")
        assert 'timed out' in timed and 'partial-output' in timed and 'shell was reset' in timed
        fiber.plugin.config['timeoutMs'] = 10000
        assert await run("Write-Output ('RESET=' + $persisted)") == 'RESET='
        abort = AbortController()
        pending = asyncio.create_task(run('Start-Sleep -Seconds 30', SimpleNamespace(agent=owner.agent, signal=abort.signal)))
        await asyncio.sleep(.2)
        abort.abort(RuntimeError('cancel-test'))
        with pytest.raises(RuntimeError, match='cancel-test'):
            await pending
        assert not ctx.get('terminals').list(owner.agent)
        await fiber.dispose()
        assert not runtime.terminals
        assert ctx.get('tools').get('pwsh', scope_of(owner.agent.ctx)) is None
    finally:
        await other.dispose()
        await owner.dispose()
        await ctx.fiber.dispose()
