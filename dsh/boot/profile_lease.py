"""OS-owned shared host/exclusive installer locks, released on process exit."""

import os


class ProfileLease:
    def __init__(self, directory, exclusive=False):
        os.makedirs(directory, exist_ok=True)
        self.stream = open(os.path.join(directory, ".dsh-python.lock"), "a+b")
        try:
            if os.name == "nt":
                import ctypes
                import msvcrt
                from ctypes import wintypes

                class Overlapped(ctypes.Structure):
                    _fields_ = [("internal", ctypes.c_size_t), ("internalHigh", ctypes.c_size_t),
                                ("offset", wintypes.DWORD), ("offsetHigh", wintypes.DWORD),
                                ("event", wintypes.HANDLE)]

                self.overlapped = Overlapped()
                api = ctypes.WinDLL("kernel32", use_last_error=True)
                lock = api.LockFileEx
                lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
                lock.restype = wintypes.BOOL
                handle = msvcrt.get_osfhandle(self.stream.fileno())
                if not lock(handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(self.overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as error:
            self.close()
            raise RuntimeError("profile is in use; stop its hosts before installing or removing plugins") from error

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
