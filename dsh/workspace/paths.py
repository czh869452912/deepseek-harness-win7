"""
Path canonicalization for workspace identity.
Aligned 1:1 with official `@deepseek-ai/dsh-workspace/src/paths`.
"""

import os


def realpath_normalize(path: str) -> str:
    """
    Canonicalize a directory path via `os.path.realpath`: trailing slashes,
    relative segments, and symlinks are all resolved.
    Raises FileNotFoundError if the path does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No such file or directory: '{path}'")
    canonical = os.path.realpath(path)
    return os.path.normpath(canonical).replace("\\", "/")


realpathNormalize = realpath_normalize
