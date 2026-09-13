"""
`SandboxedFileSystem`: the sandbox-enforcing implementation of the
`@deepseek-ai/dsh-fs` Service Definition.

1:1 with reference/packages/fs/fs-sandbox: it extends the local filesystem
backend so all text-storage mechanics - resolve, stat, read/stream, list, the
atomic write and the read-match-write edit critical section - are the local
implementation's, verbatim; this module adds only the per-call POLICY fence on
the two mutations. Reads pass through untouched: every mode permits reading.

The fence is a policy check in trusted code over a model-controlled path, NOT a
kernel boundary - the operations are the seam's own (open, rename), and only the
target path is untrusted, so canonicalize-then-contain is the complete answer to
this surface. Per call: `read-only` denies every mutation; `workspace-write`
allows a mutation only when the target canonicalizes under the policy's
workspace root or a platform temp area from the shared `writableRoots` policy;
`danger-full-access` delegates unfenced. A denial throws the structured
`FS_SANDBOX_DENIED`.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import sys
from typing import Any, Dict, Optional, Union

from dsh.fs.fs_local import FsEditOutcome, FsError, FsService, FsTarget, FsWriteOutcome
from dsh.sandbox.roots import writable_roots
from dsh.sandbox.vocabulary import DANGER_FULL_ACCESS, READ_ONLY, policy_mode

__all__ = ["SandboxedFileSystem", "is_path_under"]

_MISSING_CODES = (FileNotFoundError, NotADirectoryError)


def _is_missing(error: BaseException) -> bool:
    """Whether a stat failure means the target (or a prefix) is absent."""
    return isinstance(error, _MISSING_CODES)


def _comparable_path(path: str, case_sensitive: bool) -> str:
    return path if case_sensitive else path.lower()


def _is_lexically_under(path: str, root: str, case_sensitive: bool) -> bool:
    """Whether the canonical spelling is the root or lies beneath it."""
    comparable_target = _comparable_path(path, case_sensitive)
    comparable_root = _comparable_path(root, case_sensitive)
    if comparable_target == comparable_root:
        return True
    separator = os.sep
    prefix = comparable_root if comparable_root.endswith(separator) else comparable_root + separator
    return comparable_target.startswith(prefix)


def _stat_if_present(path: str) -> Optional[os.stat_result]:
    try:
        return os.stat(path)
    except OSError as error:
        if _is_missing(error):
            return None
        raise


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


async def is_path_under(path: str, root: str, case_sensitive: Optional[bool] = None) -> bool:
    """
    Determine whether a canonical target is a writable root or lies beneath it.

    The lexical fast path handles normal canonical spellings. When spellings
    differ, walk the target's existing ancestors and compare filesystem identity
    with the root; this recognizes Windows long-name/8.3 aliases and casing
    without weakening containment to a textual approximation.

    @param path: canonical target key, which may end in a missing suffix.
    @param root: canonical writable root.
    @param case_sensitive: whether lexical comparison preserves case; defaults to
        the host filesystem convention.
    @returns: whether the target is the root or a descendant of it.
    """
    if case_sensitive is None:
        case_sensitive = sys.platform != "win32"
    if _is_lexically_under(path, root, case_sensitive):
        return True

    root_info = _stat_if_present(root)
    if root_info is None:
        return False

    ancestor = path
    while True:
        ancestor_info = _stat_if_present(ancestor)
        if ancestor_info is not None and _same_identity(ancestor_info, root_info):
            return True
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            return False
        ancestor = parent


class SandboxedFileSystem(FsService):
    """
    Sandbox-enforcing filesystem backend.

    Registers as `ctx.fs`; loading it INSTEAD OF the bare local backend,
    together with a `ctx.sandboxPolicy`, is the whole swap - the model-facing
    tools are untouched. Its configured default mode is the capability fact
    exposed by `sandboxMode`, while an approved escalation may stamp a strictly
    wider mode for one call.
    """

    inject = ["sandboxPolicy"]

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        super().__init__(
            cwd=cfg.get("cwd"),
            diff_basis_max_bytes=cfg.get("diffBasisMaxBytes", 10 * 1024 * 1024),
        )
        self.ctx = ctx
        self._default_mode = ctx.sandboxPolicy.defaultMode if ctx is not None else READ_ONLY
        if ctx is not None and hasattr(ctx, "provide"):
            ctx.provide("fs", self)

    def apply(self, ctx: Any = None, config: Any = None) -> None:
        """The service mounts from its constructor; apply keeps the plugin shape."""
        return None

    @property
    def sandboxMode(self) -> str:
        """The deployment default mode - the capability fact the tool layer reads."""
        return self._default_mode

    @property
    def sandbox_mode(self) -> str:
        return self._default_mode

    async def writeText(
        self,
        target: Union[FsTarget, str],
        content: str,
        expected: Optional[Dict[str, Any]] = None,
        signal: Optional[Any] = None,
        sandbox_policy: Optional[Dict[str, Any]] = None,
    ) -> FsWriteOutcome:
        """Fence the write by the per-call policy, then delegate to the atomic write."""
        checked = await self._checked_target(target, sandbox_policy)
        return await FsService.writeText(self, checked, content, expected, signal)

    async def editText(
        self,
        target: Union[FsTarget, str],
        edit: Dict[str, Any],
        expected: Optional[Dict[str, Any]] = None,
        signal: Optional[Any] = None,
        sandbox_policy: Optional[Dict[str, Any]] = None,
    ) -> FsEditOutcome:
        """Fence the edit by the per-call policy, then delegate to the atomic edit."""
        checked = await self._checked_target(target, sandbox_policy)
        return await FsService.editText(self, checked, edit, expected, signal)

    async def _checked_target(
        self,
        target: Union[FsTarget, str],
        sandbox_policy: Optional[Dict[str, Any]] = None,
    ) -> FsTarget:
        """
        Enforce the per-call policy against `target` and return the EXACT target
        the mutation must use, so the checked identity is the mutated one (no
        check-here-write-there TOCTOU).

        `read-only` denies; `workspace-write` re-canonicalizes NOW (resolve
        realpaths the deepest existing ancestor, reflecting a concurrently
        swapped symlink), requires containment under a writable root, and
        returns THAT fresh target; `danger-full-access` returns the caller's
        target unfenced.
        """
        policy = sandbox_policy
        if policy is None:
            policy = self.ctx.sandboxPolicy.resolve()
        mode = policy_mode(policy)
        display_path = target.displayPath if isinstance(target, FsTarget) else self.resolve_path(target)
        if mode == DANGER_FULL_ACCESS:
            return target
        if mode == READ_ONLY:
            raise FsError(
                'cannot write "{}": file access denied under read-only mode'.format(display_path),
                "FS_SANDBOX_DENIED",
            )
        fresh = await self.resolve(display_path)
        contained = False
        for root in writable_roots(policy):
            if await is_path_under(fresh.targetKey, root):
                contained = True
                break
        if not contained:
            raise FsError(
                'cannot write "{}": file access denied under workspace-write mode'.format(display_path),
                "FS_SANDBOX_DENIED",
            )
        return fresh
