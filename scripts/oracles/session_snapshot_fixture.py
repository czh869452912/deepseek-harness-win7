import ctypes
from ctypes import wintypes
import os
import sys


def set_change_time(path, nanoseconds):
    if os.name != 'nt':
        raise RuntimeError('Controlled snapshot change-time fixture requires Windows')

    class BasicInformation(ctypes.Structure):
        _fields_ = [('creation', ctypes.c_longlong), ('access', ctypes.c_longlong),
                    ('write', ctypes.c_longlong), ('change', ctypes.c_longlong), ('attributes', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True, winmode=0)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(os.path.abspath(path), 0x100, 7, None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        information = BasicInformation()
        information.change = (nanoseconds + 11644473600000000000) // 100
        if not kernel.SetFileInformationByHandle(handle, 0, ctypes.byref(information), ctypes.sizeof(information)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


if __name__ == '__main__':
    set_change_time(sys.argv[1], int(sys.argv[2]))
