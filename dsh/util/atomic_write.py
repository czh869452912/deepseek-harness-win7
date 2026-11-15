"""Exclusive sibling replacement with bounded Windows sharing retries."""
import asyncio
import errno
import os
import secrets


async def write_file_atomic(filename, content, *, mode, dir_mode=None):
    parent = os.path.dirname(os.path.abspath(filename))
    os.makedirs(parent, mode=0o777 if dir_mode is None else dir_mode, exist_ok=True)
    temporary = filename + '.' + secrets.token_hex(6) + '.tmp'
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), mode)
        data = content.encode('utf-8') if isinstance(content, str) else content
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        delay = 0.02
        for attempt in range(9):
            try:
                os.replace(temporary, filename)
                return
            except OSError as error:
                if os.name != 'nt' or attempt == 8 or (error.errno not in (errno.EACCES, errno.EBUSY, errno.EPERM)
                        and getattr(error, 'winerror', None) not in (5, 32, 33)):
                    raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.2)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
