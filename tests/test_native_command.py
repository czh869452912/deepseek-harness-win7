import asyncio
import sys

import pytest

from dsh.core.abort import AbortController
from dsh.host import native_command


@pytest.mark.asyncio
async def test_abort_reaps_native_handoff_process(monkeypatch):
    processes = []
    spawn = asyncio.create_subprocess_exec
    async def capture(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', capture)
    controller = AbortController()
    task = asyncio.create_task(native_command.run_native(sys.executable, ['-c', 'import time; time.sleep(30)'], controller.signal))
    while not processes:
        await asyncio.sleep(.01)
    controller.abort()
    with pytest.raises(RuntimeError, match='aborted'):
        await asyncio.wait_for(task, 3)
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_windows_literal_path_is_quoted_without_shell(monkeypatch):
    calls = []
    async def run(command, args, signal):
        calls.append((command, args))
    monkeypatch.setattr(native_command, 'run_native', run)
    await native_command.open_windows("C:/dir with space/a'b;$(not-code).yaml", AbortController().signal)
    assert calls == [('powershell.exe', ['-NoProfile', '-Command', "Invoke-Item -LiteralPath 'C:/dir with space/a''b;$(not-code).yaml'"])]
