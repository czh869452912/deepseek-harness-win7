import asyncio
import os
import sys
import pytest

from dsh.subprocess.types import SubprocessTerminalSpawnSpec
from dsh.sdk.stdio import StdioInput

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='WinPTY is the Windows console substrate')


@pytest.mark.asyncio
async def test_winpty_native_console_state_unicode_and_owned_job_teardown(tmp_path):
    from dsh.subprocess.winpty import WinPtyTerminalHandle
    terminal = WinPtyTerminalHandle(SubprocessTerminalSpawnSpec(
        [os.path.join(os.environ['SystemRoot'], 'System32', 'cmd.exe'), '/q'], str(tmp_path), 24, 100, 1000), dict(os.environ))
    reader = StdioInput(terminal.output)
    chunks = []
    reader.on('data', chunks.append)
    async def wait_text(text):
        async def wait():
            while text not in b''.join(chunks).decode('utf-8', errors='replace'):
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait(), 4)
    try:
        # ECHO OFF prevents the input itself from satisfying result checks.
        await terminal.write('@echo off\r')
        await terminal.write('set DSH_PTY_TEST=retained\r')
        await terminal.write('echo [%DSH_PTY_TEST%]\r')
        await wait_text('[retained]')
        await terminal.write('echo 中文控制台\r')
        await wait_text('中文控制台')
        child_file = tmp_path / 'child.pid'
        code = "import os,time;open('child.pid','w').write(str(os.getpid()));time.sleep(30)"
        await terminal.write('start "" /b "{}" -c "{}"\r'.format(sys.executable, code))
        async def child_started():
            while not child_file.exists() or not child_file.read_text(encoding='utf-8'):
                await asyncio.sleep(.01)
        await asyncio.wait_for(child_started(), 4)
        import ctypes
        kernel = terminal.api.kernel
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong], ctypes.c_void_p
        child = terminal.api.check(kernel.OpenProcess(0x100000, False, int(child_file.read_text(encoding='utf-8'))), 'OpenProcess test child')
        assert await terminal.inspect_foreground() is None
        with pytest.raises(RuntimeError, match='unavailable'):
            await terminal.signal_foreground('SIGINT')
        await reader.close()
        try:
            await asyncio.wait_for(terminal.terminate(), 3)
            assert terminal.api.WaitForSingleObject(child, 0) == 0
        finally:
            terminal.api.CloseHandle(child)
        assert terminal.done.done()
        assert terminal.process is None and terminal.job is None and terminal.pty is None
        await terminal.terminate()
    finally:
        await reader.close()
        await terminal.terminate()


@pytest.mark.asyncio
async def test_winpty_failed_spawn_cleans_partial_native_resources(tmp_path):
    from dsh.subprocess.winpty import WinPtyTerminalHandle
    with pytest.raises(RuntimeError, match='winpty_spawn'):
        WinPtyTerminalHandle(SubprocessTerminalSpawnSpec(
            [str(tmp_path / 'no-program.exe')], str(tmp_path), 24, 80, 1000), dict(os.environ))
