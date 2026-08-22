"""
Zero-dependency FileLock utility (`dsh.cordis.file_lock`).
Falls back to stdlib `msvcrt` (Windows) / `fcntl` (POSIX) + `threading.RLock`
when third-party `filelock` module is not installed.
"""

import os
import sys
import threading

try:
    from filelock import FileLock
except ImportError:
    class FileLock:
        """Zero-dependency fallback FileLock using stdlib msvcrt/fcntl + threading RLock."""

        _locks = {}
        _lock_guard = threading.Lock()

        def __init__(self, lock_file: str, timeout: float = None):
            self.lock_file = str(lock_file)
            self.timeout = timeout
            self._fd = None
            with FileLock._lock_guard:
                if self.lock_file not in FileLock._locks:
                    FileLock._locks[self.lock_file] = threading.RLock()
                self._rlock = FileLock._locks[self.lock_file]

        def acquire(self, timeout: float = None, poll_interval: float = 0.05):
            self._rlock.acquire()
            try:
                parent = os.path.dirname(os.path.abspath(self.lock_file))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                self._fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR)
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        os.write(self._fd, b"\0")
                        os.lseek(self._fd, 0, os.SEEK_SET)
                        msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
                    except Exception:
                        pass
                else:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_EX)
            except Exception:
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except Exception:
                        pass
                    self._fd = None
                try:
                    self._rlock.release()
                except RuntimeError:
                    pass
                raise
            return self

        def release(self):
            if self._fd is not None:
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        try:
                            msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                        except Exception:
                            pass
                    else:
                        import fcntl
                        try:
                            fcntl.flock(self._fd, fcntl.LOCK_UN)
                        except Exception:
                            pass
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            try:
                self._rlock.release()
            except RuntimeError:
                pass

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.release()
