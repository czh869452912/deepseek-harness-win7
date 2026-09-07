"""
Zero-dependency FileLock utility (`dsh.cordis.file_lock`).
Falls back to stdlib `msvcrt` (Windows) / `fcntl` (POSIX) + `threading.RLock`
when third-party `filelock` module is not installed.
"""

import asyncio
import os
import sys
import threading
import time
from typing import Any

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


_async_locks = {}
_async_guard = threading.Lock()


def _get_async_lock(key: str) -> asyncio.Lock:
    with _async_guard:
        if key not in _async_locks:
            _async_locks[key] = asyncio.Lock()
        return _async_locks[key]


async def with_file_lock(lock_path: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Acquire file lock around an async or sync callable matching reference withFileLock."""
    wait_ms = kwargs.pop("waitMs", kwargs.pop("wait_ms", 2000))
    lock_file = lock_path if lock_path.endswith(".lock") else f"{lock_path}.lock"
    norm_key = os.path.normcase(os.path.abspath(lock_file))
    alock = _get_async_lock(norm_key)

    await alock.acquire()
    try:
        deadline = time.time() + (wait_ms / 1000.0)
        delay = 0.02
        acquired_os_lock = False
        fd = -1
        while True:
            try:
                parent = os.path.dirname(os.path.abspath(lock_file))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
                acquired_os_lock = True
                break
            except (FileExistsError, PermissionError):
                if time.time() >= deadline:
                    raise RuntimeError(f"atomic-write: timed out waiting for the writer lock at {lock_file}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.2)
            except Exception:
                raise

        try:
            res = fn(*args, **kwargs)
            if asyncio.iscoroutine(res):
                return await res
            return res
        finally:
            if acquired_os_lock:
                if fd != -1:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
                try:
                    os.unlink(lock_file)
                except Exception:
                    pass
    finally:
        alock.release()
