"""OS-owned shared host/exclusive installer locks, released on process exit."""

import os
from contextlib import contextmanager
import threading


class _FileLease:
    def __init__(self, directory, exclusive=False, name='.dsh-python.lock'):
        os.makedirs(directory, exist_ok=True)
        self.stream = open(os.path.join(directory,name), "a+b")
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


class ProfileLease:
    """Gate every admission so a single host can safely promote its own lease.

    The admission lock stays held while promotion releases/reacquires the
    lifetime lock, so another installer cannot occupy that gap. Other existing
    hosts cause promotion to refuse; the original shared lease is restored.
    """
    def __init__(self,directory,exclusive=False):
        self.directory=os.path.normcase(os.path.realpath(directory));self.exclusive=exclusive
        self._guard=threading.RLock();self._window=False;self._lease=None
        with _FileLease(self.directory,True,'.dsh-python-gate.lock'):
            self._lease=_FileLease(self.directory,exclusive)

    @property
    def stream(self):return None if self._lease is None else self._lease.stream

    def assert_exclusive(self,directory):
        if self.stream is None or not self.exclusive or self.directory!=os.path.normcase(os.path.realpath(directory)):
            raise RuntimeError('native package transaction requires its owned exclusive profile lease')

    @contextmanager
    def exclusive_window(self):
        with self._guard:
            if self.stream is None:raise RuntimeError('profile lease is closed')
            if self.exclusive or self._window:raise RuntimeError('profile lease promotion cannot be nested')
            with _FileLease(self.directory,True,'.dsh-python-gate.lock'):
                self._lease.close();self._lease=None
                try:
                    self._lease=_FileLease(self.directory,True);self.exclusive=True;self._window=True
                    yield self
                finally:
                    if self._lease is not None:self._lease.close()
                    self._lease=_FileLease(self.directory,False);self.exclusive=False;self._window=False

    def close(self):
        with self._guard:
            if self._window:raise RuntimeError('cannot close a profile lease during its mutation window')
            if self._lease is not None:self._lease.close();self._lease=None

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


@contextmanager
def package_write_lease(directory,lease=None):
    """A supplied lease never transfers ownership to the package store."""
    if lease is not None:
        if not isinstance(lease,ProfileLease):raise RuntimeError('native package transaction requires an owned profile lease')
        with lease._guard:
            lease.assert_exclusive(directory);yield lease
    else:
        with ProfileLease(directory,exclusive=True) as owned:yield owned
