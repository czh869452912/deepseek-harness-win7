import ctypes
from ctypes import wintypes


_KERNEL = None
FILETIME_EPOCH = 116444736000000000


class BasicInfo(ctypes.Structure):
    _fields_ = [('creation', ctypes.c_longlong), ('access', ctypes.c_longlong),
        ('write', ctypes.c_longlong), ('change', ctypes.c_longlong), ('attributes', wintypes.DWORD)]


class HandleInfo(ctypes.Structure):
    _fields_ = [('attributes', wintypes.DWORD), ('creation', wintypes.FILETIME),
        ('access', wintypes.FILETIME), ('write', wintypes.FILETIME), ('volume', wintypes.DWORD),
        ('size_high', wintypes.DWORD), ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
        ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]


class NodeStat:
    def __init__(self, original, basic, identity):
        self.original = original
        self.st_ctime_ns = (basic.change - FILETIME_EPOCH) * 100
        self.st_mtime_ns = (basic.write - FILETIME_EPOCH) * 100
        self.st_ctime = self.st_ctime_ns / 1000000000
        self.st_mtime = self.st_mtime_ns / 1000000000
        self.st_dev = identity.volume
        self.st_ino = (identity.index_high << 32) | identity.index_low
        self.st_size = (identity.size_high << 32) | identity.size_low

    def __getattr__(self, name):
        return getattr(self.original, name)


def kernel():
    global _KERNEL
    if _KERNEL is None:
        selected = ctypes.WinDLL('kernel32', use_last_error=True)
        selected.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        selected.CreateFileW.restype = wintypes.HANDLE
        selected.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        selected.GetFileInformationByHandleEx.restype = wintypes.BOOL
        selected.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(HandleInfo)]
        selected.GetFileInformationByHandle.restype = wintypes.BOOL
        selected.CloseHandle.argtypes = [wintypes.HANDLE]
        selected.CloseHandle.restype = wintypes.BOOL
        _KERNEL = selected
    return _KERNEL


def node_stat(path, original, follow=True):
    selected = kernel()
    flags = 0x02000000 | (0 if follow else 0x00200000)
    handle = selected.CreateFileW(path, 0x80, 7, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        identity, basic = HandleInfo(), BasicInfo()
        if not selected.GetFileInformationByHandle(handle, ctypes.byref(identity)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not selected.GetFileInformationByHandleEx(handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)):
            raise ctypes.WinError(ctypes.get_last_error())
        return NodeStat(original, basic, identity)
    finally:
        selected.CloseHandle(handle)
