"""Exclusive durable publication using Win7 APIs or POSIX directory fsync."""
import os
import tempfile


def _windows_path(path):
    path = os.path.abspath(path)
    if path.startswith('\\\\?\\'):
        return path
    return '\\\\?\\UNC\\' + path[2:] if path.startswith('\\\\') else '\\\\?\\' + path


def _move_new_windows(source, target):
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    move = api.MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    # No REPLACE_EXISTING or COPY_ALLOWED: preserve competing publishers and
    # remain on the staging volume. MOVEFILE_WRITE_THROUGH is available on Win7.
    if not move(_windows_path(source), _windows_path(target), 0x8):
        raise ctypes.WinError(ctypes.get_last_error())


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_durable_directory(path):
    path = os.path.abspath(path)
    if os.path.isdir(path):
        return
    parent = os.path.dirname(path)
    if parent == path:
        raise NotADirectoryError(path)
    ensure_durable_directory(parent)
    if os.name == 'nt':
        staging = tempfile.mkdtemp(prefix='.dsh-mkdir-', dir=parent)
        try:
            _move_new_windows(staging, path)
        except OSError as error:
            os.rmdir(staging)
            if getattr(error, 'winerror', None) not in (80, 183) or not os.path.isdir(path):
                raise
    else:
        os.makedirs(path, mode=0o700, exist_ok=True)
        _sync_directory(parent)


def publish_new_file(staging, target):
    if os.name == 'nt':
        _move_new_windows(staging, target)
    else:
        os.link(staging, target)
        _sync_directory(os.path.dirname(target))


def discard_staging(path):
    # Cleanup cannot turn an already committed publication into a retry.
    try:
        os.unlink(path)
    except OSError:
        pass
