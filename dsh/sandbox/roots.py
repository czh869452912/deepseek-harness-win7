"""
The writable-root derivation shared by every enforcement dialect that expresses
a mode as a canonical allow-list.

1:1 with reference/packages/sandbox/sandbox/src/roots.ts: `workspace-write`
means "the workspace root plus the platform temp areas", and this module is that
meaning's one home, so the in-process filesystem fence
(`@deepseek-ai/dsh-fs-sandbox`) and the process backends derive their allow-list
from the same function.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import tempfile
from typing import Any, List

__all__ = ["canonical_path", "writable_roots"]


def canonical_path(path: str) -> str:
    """
    Resolve a granted root to the path the enforcement layer actually compares.

    The reference calls `realpathSync.native`, which follows the filesystem's
    component-by-component lookup and throws when the path (or a prefix) is
    missing; a throwing resolution returns the spelling as-is, because a missing
    root matches nothing until it exists and inventing a fallback would grant a
    path the caller never named.

    @param path: the root as configured or platform-reported.
    @returns: the canonical path, or the spelling as-is when resolution fails.
    """
    try:
        os.lstat(path)
    except OSError:
        # `realpathSync.native` throws ENOENT/ENOTDIR here; the spelling stays.
        return path
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def writable_roots(policy: Any) -> List[str]:
    """
    The roots one confined execution may WRITE under, as a canonical,
    deduplicated allow-list.

    `read-only` allows nothing; `workspace-write` allows the policy's workspace
    root, the host `/tmp`, and the per-user platform temp directory (`os.tmpdir()`
    in the reference - the real temp area for mkstemp-family tools; omitting it
    would deny what the mode promises).

    @param policy: the file-effect policy to derive the allow-list from.
    @returns: the canonical writable roots; empty exactly under `read-only`.
    """
    from dsh.sandbox.vocabulary import WORKSPACE_WRITE, policy_mode, policy_workspace_root

    if policy_mode(policy) != WORKSPACE_WRITE:
        return []
    roots: List[str] = []
    for spelling in (policy_workspace_root(policy), "/tmp", tempfile.gettempdir()):
        canonical = canonical_path(spelling)
        if canonical not in roots:
            roots.append(canonical)
    return roots
