import os
import sys

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime,SubprocessExecutableNotFoundError


@pytest.mark.asyncio
async def test_target_shell_profiles_discovery_and_actual_lookup(tmp_path):
    from scripts.rc022_terminal_shells_probe import observe
    rows={row['name']:row for row in await observe(tmp_path)}
    assert rows['default-windows-0']['value'] == dict(path='cmd.exe',name='cmd.exe',args=[])
    assert rows['default-posix-1']['value']['args'] == ['-i']
    assert rows['default-windows-2']['value']['args'] == ['-NoLogo']
    assert [shell['name'] for shell in rows['discovered']['value']] == ['Configured','powershell.exe','PWSH.EXE','cmd']
    assert rows['find-Bash.exe']['value']['name'] == 'Configured'
    assert rows['transport-failure']['message'] == 'transport offline'
    assert rows['local-path']['value'].endswith('first\\dsh-shell.EXE')
    assert rows['lookup-absent']['typed'] and rows['lookup-directory']['typed']
    assert rows['lookup-absent']['message'] == 'subprocess-local: command "absent" was not found on PATH'
    assert rows['lookup-directory']['message'] == 'subprocess-local: command "directory" was not found on PATH'
    assert not rows['lookup-./relative']['typed'] and not rows['lookup-']['typed']
    assert rows['lookup-cancellation']['same']


@pytest.mark.asyncio
async def test_resolution_rechecks_signal_after_async_inspection(tmp_path,monkeypatch):
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx);controller=AbortController();failure=RuntimeError('aborted after stat')
    def executable(path):controller.abort(failure);return True
    monkeypatch.setattr(os.path,'isfile',executable)
    try:
        with pytest.raises(RuntimeError) as caught:await runtime.resolveExecutable(sys.executable,None,controller.signal)
        assert caught.value is failure
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_terminal_environment_uses_execution_default_and_preserves_abort(monkeypatch):
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx);controller=AbortController();failure=RuntimeError('environment cancelled')
    monkeypatch.setenv('ComSpec','C:\\Windows\\System32\\cmd.exe')
    try:
        assert await runtime.terminalEnvironment(controller.signal) == dict(platform='windows',defaultShell='C:\\Windows\\System32\\cmd.exe')
        controller.abort(failure)
        with pytest.raises(RuntimeError) as caught:await runtime.terminalEnvironment(controller.signal)
        assert caught.value is failure
    finally:await ctx.fiber.dispose()
