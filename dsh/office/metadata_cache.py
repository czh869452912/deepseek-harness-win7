"""Bounded physical storage; the original SDK owns cache validation and encoding."""
import os
from pathlib import Path
import tempfile

from .errors import OfficeKitError
from .file_transaction import read_document


def read_cache(directory, maximum, signal):
    if directory is False:
        return None
    try:
        return read_document(str(Path(directory) / 'font-metadata.json'), maximum, signal)
    except (OSError, OfficeKitError):
        return None


def publish_cache(directory, data, maximum, signal):
    if directory is False or not isinstance(data, bytes) or len(data) > maximum:
        return
    owned = None
    try:
        signal.throwIfAborted()
        os.makedirs(directory, mode=0o700, exist_ok=True)
        descriptor, owned = tempfile.mkstemp(prefix='.font-metadata-', suffix='.tmp', dir=directory)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        signal.throwIfAborted()
        os.replace(owned, str(Path(directory) / 'font-metadata.json'))
        owned = None
    except OSError:
        pass
    finally:
        if owned is not None:
            try:
                os.unlink(owned)
            except OSError:
                pass
