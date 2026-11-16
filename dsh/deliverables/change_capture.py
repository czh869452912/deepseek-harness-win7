"""Bounded content-addressed whole-file captures owned by one recorder."""
import asyncio
import hashlib
import os
import stat


def _capture_file(absolute, directory, max_bytes):
    try:
        source = open(absolute, 'rb')
    except FileNotFoundError:
        return dict(kind='absent')
    with source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            return None
        payload = source.read(max_bytes+1)
        if len(payload) > max_bytes:
            return dict(kind='oversized')
    file = os.path.join(directory, hashlib.sha1(payload).hexdigest())
    os.makedirs(directory, exist_ok=True)
    try:
        with open(file, 'xb') as captured:
            captured.write(payload)
    except FileExistsError:
        pass
    return dict(kind='file', file=file, binary=b'\0' in payload[:8000])


async def captureFile(absolute, directory, maxBytes):
    pending = asyncio.get_running_loop().run_in_executor(None, _capture_file, absolute, directory, maxBytes)
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        # Python Task cancellation cannot stop an OS file read. Retain its
        # ownership until the handle closes and any content write settles.
        await asyncio.shield(pending)
        raise


def sameCapture(a, b):
    if a['kind'] == 'absent' or b['kind'] == 'absent':
        return a['kind'] == b['kind']
    return a['kind'] == 'file' and b['kind'] == 'file' and a['file'] == b['file']
