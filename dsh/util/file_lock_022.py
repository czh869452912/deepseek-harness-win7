"""Pinned atomic-write writer coordination, including proven dead-PID takeover."""
import asyncio
import errno
import hashlib
import os
import re
import time

from dsh.core.abort import NEVER_ABORTED


def holder_exited(record):
    if not re.fullmatch(r'[0-9]+\n', record):
        return False
    pid = int(record)
    if pid == 0 or pid > 0x7fffffff or pid == os.getpid():
        return False
    if os.name == 'nt':
        # os.kill(pid, 0) can terminate a Windows process on Python 3.8.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                code = wintypes.DWORD()
                return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value != 259
            finally:
                kernel.CloseHandle(handle)
        return ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER; access denied proves nothing.
    try:
        os.kill(pid, 0)
    except OSError as error:
        return error.errno == errno.ESRCH
    return False


def read_record(path):
    try:
        with open(path, encoding='utf-8') as stream:
            return stream.read()
    except (OSError, UnicodeError):
        return None


def create_record(path):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
        stream.write(str(os.getpid())+'\n')


def remove(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def take_over(path):
    record = read_record(path)
    if record is None or not holder_exited(record):
        return False
    claim = path+'.takeover-'+hashlib.sha256(record.encode('utf-8')).hexdigest()[:16]
    try:
        create_record(claim)
    except OSError as error:
        if error.errno in (errno.EEXIST, errno.EPERM, errno.EACCES):
            return False
        raise
    try:
        if read_record(path) != record or not holder_exited(record):
            return False
        try:
            remove(path)
            return True
        except OSError:
            return False
    finally:
        try:
            remove(claim)
        except OSError:
            pass


async def wait(delay, signal):
    signal.throwIfAborted()
    future = asyncio.get_running_loop().create_future()
    timer = asyncio.get_running_loop().call_later(delay, lambda: None if future.done() else future.set_result(None))
    detach = signal.add_listener('abort', lambda _: None if future.done() else future.set_result(None))
    try:
        await future
        signal.throwIfAborted()
    finally:
        timer.cancel()
        detach()


async def with_file_lock(filename, operation, wait_ms=2000, signal=NEVER_ABORTED):
    path = str(filename)+'.lock'
    deadline, delay, retried = time.time()+wait_ms/1000, 0.02, False
    while True:
        signal.throwIfAborted()
        try:
            create_record(path)
            break
        except OSError as error:
            contention = error.errno == errno.EEXIST
            if error.errno in (errno.EPERM, errno.EACCES):
                try:
                    os.lstat(path)
                    contention = True
                except OSError:
                    pass
            if contention:
                if take_over(path):
                    continue
            elif os.name == 'nt' and error.errno in (errno.EPERM, errno.EACCES) and not retried:
                retried = True
            else:
                raise
        if time.time() >= deadline:
            raise RuntimeError('atomic-write: timed out waiting for the writer lock at '+path)
        await wait(delay, signal)
        delay = min(delay*2, 0.2)
    try:
        signal.throwIfAborted()
        return await operation()
    finally:
        remove(path)
