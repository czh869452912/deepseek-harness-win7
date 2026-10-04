from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
import shutil
import time


@lru_cache(maxsize=1)
def _windows_api():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True, winmode=0)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _extended_path(path):
    absolute = os.path.abspath(path)
    if len(absolute) >= 248 and not absolute.startswith('\\\\?\\'):
        return '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute
    return absolute


def _open_delete_handle(kernel, path, deadline):
    failure = None
    while True:
        handle = kernel.CreateFileW(_extended_path(path), 0x10000, 7, None, 3, 0x02000000, None)
        if handle != wintypes.HANDLE(-1).value:
            return handle
        error = ctypes.WinError(ctypes.get_last_error())
        if error.winerror not in (32, 33):
            raise error
        if failure is None:
            failure = error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise failure
        time.sleep(min(0.02, remaining))


@contextmanager
def directory_mutation(path, timeout=1.0, drain_children=False):
    if os.name != 'nt':
        yield
        return
    kernel = _windows_api()
    deadline = time.monotonic() + timeout
    handles = []
    failure = None
    try:
        if os.path.islink(path) or getattr(os.lstat(path), 'st_reparse_tag', 0):
            raise ValueError('owned directory mutation refuses links or junctions')
        handles.append(_open_delete_handle(kernel, path, deadline))
        if drain_children:
            for directory, directories, files in os.walk(path):
                for name in directories + files:
                    child = os.path.join(directory, name)
                    if os.path.islink(child) or getattr(os.lstat(child), 'st_reparse_tag', 0):
                        raise ValueError('owned directory mutation refuses links or junctions')
                    handles.append(_open_delete_handle(kernel, child, deadline))
            while len(handles) > 1:
                if not kernel.CloseHandle(handles[-1]):
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.pop()
        yield
    except BaseException as error:
        failure = error
        raise
    finally:
        close_error = None
        for handle in reversed(handles):
            if not kernel.CloseHandle(handle) and close_error is None:
                close_error = ctypes.WinError(ctypes.get_last_error())
        if failure is None and close_error is not None:
            raise close_error


def replace_directory(source, destination):
    deadline = time.monotonic() + 1.0
    with directory_mutation(source):
        failure = None
        while True:
            try:
                os.replace(source, destination)
                return
            except PermissionError as error:
                if os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33):
                    raise
                if failure is None:
                    failure = error
                if os.path.lexists(destination):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise failure
                time.sleep(min(0.02, remaining))


def remove_directory(path):
    with directory_mutation(path, drain_children=True):
        shutil.rmtree(path)
