import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _windows_api():
    import ctypes
    from ctypes import wintypes
    class BasicInformation(ctypes.Structure):
        _fields_ = [('creation',ctypes.c_longlong),('access',ctypes.c_longlong),
                    ('write',ctypes.c_longlong),('change',ctypes.c_longlong),('attributes',wintypes.DWORD)]
    class HandleInformation(ctypes.Structure):
        _fields_ = [('attributes',wintypes.DWORD),('creation',wintypes.FILETIME),
                    ('access',wintypes.FILETIME),('write',wintypes.FILETIME),
                    ('volume',wintypes.DWORD),('size_high',wintypes.DWORD),('size_low',wintypes.DWORD),
                    ('links',wintypes.DWORD),('index_high',wintypes.DWORD),('index_low',wintypes.DWORD)]
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                                   ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE,ctypes.POINTER(HandleInformation)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel, BasicInformation, HandleInformation, ctypes


def filesystem_identity(path):
    if os.name != 'nt':
        identity = os.stat(path)
        return dict(dev=identity.st_dev,ino=identity.st_ino,size=identity.st_size,
                    mtimeNs=identity.st_mtime_ns,ctimeNs=identity.st_ctime_ns,
                    birthtimeNs=getattr(identity,'st_birthtime_ns',identity.st_ctime_ns))
    kernel, BasicInformation, HandleInformation, ctypes = _windows_api()
    absolute = os.path.abspath(path)
    if len(absolute) >= 248 and not absolute.startswith('\\\\?\\'):
        absolute = '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute
    handle = kernel.CreateFileW(absolute,0x80,7,None,3,0x02000000,None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    failure = None
    try:
        basic = BasicInformation()
        information = HandleInformation()
        if not kernel.GetFileInformationByHandle(handle,ctypes.byref(information)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.GetFileInformationByHandleEx(handle,0,ctypes.byref(basic),ctypes.sizeof(basic)):
            raise ctypes.WinError(ctypes.get_last_error())
        epoch = 11644473600000000000
        return dict(dev=information.volume,ino=(information.index_high << 32) | information.index_low,
                    size=(information.size_high << 32) | information.size_low,
                    mtimeNs=basic.write*100-epoch,ctimeNs=basic.change*100-epoch,
                    birthtimeNs=basic.creation*100-epoch)
    except BaseException as error:
        failure = error
        raise
    finally:
        closed = kernel.CloseHandle(handle)
        if not closed and failure is None:
            raise ctypes.WinError(ctypes.get_last_error())


def file_revision(path):
    identity = filesystem_identity(path)
    return ':'.join(str(identity[name]) for name in ('dev','ino','size','mtimeNs','ctimeNs'))
