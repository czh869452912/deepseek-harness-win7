"""Win7 inherited-Job fallback: own a Host even while its Python GIL is blocked.

This process runs only trusted lifetime supervision. It never evaluates source.
Kernel handles, opened before the ready signal, avoid PID reuse races.
"""
import ctypes
from ctypes import wintypes
import sys


def main(parent_pid, worker_pid):
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.restype = wintypes.HANDLE
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
    api.WaitForMultipleObjects.restype = wintypes.DWORD
    worker = api.OpenProcess(0x100001, False, worker_pid)  # SYNCHRONIZE | TERMINATE
    if not worker:
        raise ctypes.WinError(ctypes.get_last_error())
    parent = api.OpenProcess(0x100000, False, parent_pid)
    try:
        if not parent:
            api.TerminateProcess(worker, 1)
            raise ctypes.WinError(ctypes.get_last_error())
        handles = (wintypes.HANDLE * 2)(parent, worker)
        sys.stdout.buffer.write(b'ready\n')
        sys.stdout.buffer.flush()
        result = api.WaitForMultipleObjects(2, handles, False, 0xffffffff)
        if result == 0:
            if not api.TerminateProcess(worker, 1):
                # It may have exited concurrently with its owner.
                if api.WaitForMultipleObjects(1, (wintypes.HANDLE * 1)(worker), False, 0) != 0:
                    raise ctypes.WinError(ctypes.get_last_error())
        elif result != 1:
            api.TerminateProcess(worker, 1)
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if parent:
            api.CloseHandle(parent)
        api.CloseHandle(worker)


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]))
