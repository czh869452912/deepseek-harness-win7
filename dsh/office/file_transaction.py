"""Owned SDK file transactions; drain disk work before releasing its owner."""
import asyncio
import os
import stat

from dsh.cordis.errors import AggregateError
from .errors import OfficeKitError
from .font_volume import _fstat
from .outputs import _native, _remove_tree


async def disk_call(function, *args):
    """Cancellation must not leave a thread writing into released scratch."""
    task = asyncio.ensure_future(asyncio.get_running_loop().run_in_executor(None, function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            except BaseException:
                break
        if not task.cancelled():
            task.exception()
        raise


def _version(info):
    # Node's non-bigint Stats exposes floating millisecond timestamps.
    return info.st_size, info.st_mtime_ns / 1000000, info.st_ctime_ns / 1000000


def read_document(path, limit, signal, role='input'):
    """SDK readBounded: regular, bounded, complete and stable through the read."""
    signal.throwIfAborted()
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(_native(path), flags)
    try:
        before = _fstat(descriptor)
        invalid = 'invalid-document' if role == 'input' else 'invalid-output'
        if not stat.S_ISREG(before.st_mode) or role == 'input' and before.st_size < 1:
            raise OfficeKitError(invalid, 'Document must be a nonempty regular file.')
        if before.st_size > limit:
            raise OfficeKitError(role + '-too-large', 'Document exceeds its ' + role + ' byte limit.')
        chunks, remaining = [], before.st_size
        while remaining:
            signal.throwIfAborted()
            data = os.read(descriptor, min(remaining, 1024 * 1024))
            if not data:
                raise OfficeKitError(invalid, 'Document was truncated while reading.')
            chunks.append(data)
            remaining -= len(data)
        if _version(before) != _version(_fstat(descriptor)):
            raise OfficeKitError(invalid, 'Document changed while reading.')
        signal.throwIfAborted()
        return b''.join(chunks)
    finally:
        os.close(descriptor)


class FileExport:
    """Create wx before input read. Only a successfully opened file is owned."""
    def __init__(self, path):
        self.path, self.descriptor, self.succeeded = path, None, False

    def open(self):
        self.descriptor = os.open(_native(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)

    def write(self, data, signal):
        signal.throwIfAborted()
        view = memoryview(data)
        while view:
            signal.throwIfAborted()
            size = os.write(self.descriptor, view[:1024 * 1024])
            if not size:
                raise OSError('Document output write made no progress.')
            view = view[size:]
        signal.throwIfAborted()
        self.succeeded = True

    def close(self, failure=None):
        if self.descriptor is None:
            return
        descriptor, self.descriptor = self.descriptor, None
        errors = []
        try:
            os.close(descriptor)
        except OSError as cause:
            errors.append(cause)
        if not self.succeeded:
            try:
                os.unlink(_native(self.path))
            except OSError as cause:
                errors.append(cause)
        if errors:
            raise AggregateError(([failure] if failure is not None else []) + errors,
                                 'LibreOffice conversion cleanup failed.')


class ImageExport:
    """Own a newly created directory, including partially written image batches."""
    def __init__(self, path):
        self.path, self.owned, self.succeeded = path, False, False

    def open(self):
        os.mkdir(_native(self.path), 0o700)
        self.owned = True

    def close(self):
        if self.owned and not self.succeeded:
            try:
                _remove_tree(self.path)
            except OSError as cause:
                raise AggregateError([cause], 'Image batch cleanup failed.')
        self.owned = False
