import asyncio
import os

import pytest

from dsh.cordis.context import Context
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.sandbox.local import LocalSandboxProvider
from dsh.sandbox.sandbox_policy import SandboxPolicyService
from dsh.sandbox.vocabulary import SandboxUnavailableError
from dsh.shell.pwsh_executor import SandboxPwshExecutor, runner_failure


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell integration')
@pytest.mark.asyncio
async def test_shell_real_confinement_timeout_background_and_cancel(tmp_path):
    ctx = Context()
    fibers = []
    for plugin, config in [(LocalSubprocessRuntime, {}), (LocalSandboxProvider, {}),
                           (SandboxPolicyService, {'mode': 'workspace-write', 'workspaceRoot': str(tmp_path)}),
                           (SandboxPwshExecutor, {'cwd': str(tmp_path), 'graceMs': 50})]:
        fiber = ctx.plugin(plugin, config)
        await fiber.await_settled()
        fibers.append(fiber)
    shell = ctx.get('shell')
    try:
        result = await shell.run(shell.resolve({'command': "[IO.File]::WriteAllText('created','yes'); Write-Output '你好'"}))
        assert result['exitCode'] == 0, result
        assert '你好' in result['stdout']['text']
        assert (tmp_path / 'created').read_text() == 'yes'
        denied = await shell.run(shell.resolve({'command': "$ErrorActionPreference='Stop'; Set-Content -LiteralPath 'created' -Value 'no'",
                                                'sandboxPolicy': {'mode': 'read-only', 'workspaceRoot': str(tmp_path)}}))
        assert denied['exitCode'] != 0 and denied['sandbox']['denied'], denied['stderr']['text']
        assert (tmp_path / 'created').read_text() == 'yes'
        timeout = await shell.run(shell.resolve({'command': 'Start-Sleep -Seconds 20', 'timeoutMs': 400}))
        assert timeout['timedOut'] and not timeout['aborted']
        process = shell.start(shell.resolve({'command': "Start-Sleep -Milliseconds 400; Write-Output 'done'", 'timeoutMs': 1}))
        await asyncio.wait_for(process.done, 8)
        assert process.status == 'completed'
        assert 'done' in process.readOutput()['delta']
        assert process.readOutput()['delta'] == ''
        signal = asyncio.Event()
        pending = asyncio.create_task(shell.run(shell.resolve({'command': 'Start-Sleep -Seconds 20', 'signal': signal})))
        await asyncio.sleep(.3)
        signal.set()
        cancelled = await asyncio.wait_for(pending, 5)
        assert cancelled['aborted'] and not cancelled['timedOut']
        failed = await shell.run(shell.resolve({'command': "Write-Error 'windows-acl-run: pretend'; exit 2"}))
        assert failed['exitCode'] == 2
        with pytest.raises(SandboxUnavailableError):
            await shell.run(shell.resolve({'command': "Write-Error 'windows-acl-run: actual'; exit 127"}))
    finally:
        for fiber in reversed(fibers):
            await fiber.dispose()


def test_runner_fatal_line_excludes_information_and_requires_exit_gate():
    rules = [{'allowedExitCodes': [125], 'fatalSignatures': ['runner: ', '  '],
              'informationalLines': ['runner: partial enforcement']}]
    stderr = 'runner: partial enforcement\nrunner: refused permission denied'
    assert runner_failure(125, stderr, rules) == 'runner: refused permission denied'
    assert runner_failure(1, stderr, rules) is None
    assert runner_failure(None, stderr, rules) is None
