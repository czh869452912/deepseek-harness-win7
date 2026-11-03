"""Real WinForms owner/z-order and cancellation through the production runner."""
import asyncio
import ctypes
from ctypes import wintypes
import os
import subprocess

import pytest

from dsh.core.abort import AbortController
from dsh.cordis.context import Context
from dsh.host.directory_picker.native import NativeDirectoryPickerService


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows native dialog')


@pytest.fixture(scope='module', autouse=True)
def interactive_windows_session():
    if os.name == 'nt':
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                 '[Environment]::UserInteractive'], capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr
        if result.stdout.strip() == b'False':
            pytest.skip('Real WinForms dialogs require an interactive Windows session')
        assert result.stdout.strip() == b'True', result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['select-folder', 'cancel-dialog', 'abort-request'])
async def test_dialog_is_owned_topmost_and_child_is_reaped(monkeypatch, tmp_path, action):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongW.restype = wintypes.LONG
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindow.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    user.SendMessageW.restype = ctypes.c_ssize_t
    children = []
    spawn = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', capture)
    controller = AbortController()
    ctx = Context()
    service = NativeDirectoryPickerService(ctx)
    task = asyncio.create_task(service.pick_native(controller.signal))
    dialog = None
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def inspect(hwnd, _):
        nonlocal dialog
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(hwnd, name, len(name))
        if children and pid.value == children[0].pid and name.value == '#32770' and user.IsWindowVisible(hwnd):
            dialog = hwnd
        return True

    try:
        for _ in range(300):
            user.EnumWindows(inspect, 0)
            if dialog or task.done():
                break
            await asyncio.sleep(.05)
        assert dialog, 'Native picker did not become visible'
        owner = user.GetWindow(dialog, 4)  # GW_OWNER
        assert owner, 'Dialog must not be orphaned behind the browser'
        assert user.GetWindowLongW(owner, -20) & 0x8  # WS_EX_TOPMOST
        assert user.GetWindowLongW(dialog, -20) & 0x8
        if action == 'abort-request':
            controller.abort()
            with pytest.raises(RuntimeError, match='aborted'):
                await asyncio.wait_for(task, 5)
        elif action == 'cancel-dialog':
            assert user.PostMessageW(dialog, 0x10, 0, 0)  # WM_CLOSE = Cancel
            assert await asyncio.wait_for(task, 5) is None
        else:
            selected = tmp_path / '中文 workspace'
            selected.mkdir()
            buffer = ctypes.create_unicode_buffer(str(selected))
            # WM_USER messages do not marshal pointers across processes. The
            # folder string must live in the chooser child's address space.
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
            kernel.VirtualAllocEx.restype = ctypes.c_void_p
            kernel.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
            kernel.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x28, False, children[0].pid)  # VM_OPERATION | VM_WRITE
            assert handle
            remote = None
            try:
                remote = kernel.VirtualAllocEx(handle, None, ctypes.sizeof(buffer), 0x3000, 4)
                assert remote
                assert kernel.WriteProcessMemory(handle, remote, buffer, ctypes.sizeof(buffer), None)
                user.SendMessageW(dialog, 0x467, 1, remote)  # BFFM_SETSELECTIONW
            finally:
                if remote:
                    kernel.VirtualFreeEx(handle, remote, 0, 0x8000)
                kernel.CloseHandle(handle)
            assert user.PostMessageW(dialog, 0x111, 1, 0)  # WM_COMMAND / IDOK
            assert await asyncio.wait_for(task, 5) == str(selected)
        assert children[0].returncode is not None
        assert not user.IsWindow(dialog) and not user.IsWindow(owner)
        assert not controller.signal._listeners
    finally:
        if not task.done():
            controller.abort()
        await asyncio.gather(task, return_exceptions=True)
        await ctx.fiber.dispose()
