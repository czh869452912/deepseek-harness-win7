"""
1:1 parity suite for the sandbox capability vocabulary and writable-root
derivation (`dsh/sandbox/roots.py`, `dsh/sandbox/vocabulary.py`).

Upstream is reference/packages/sandbox/sandbox/tests/roots.spec.ts and
.../vocabulary.spec.ts: `canonicalPath` resolves an existing path and keeps an
unresolvable spelling as-is; `writableRoots` is the mode's meaning as a
canonical, deduplicated allow-list; `SandboxUnavailableError` carries the
structured `{ name, code }` identity consumers key on.
"""

import os
import tempfile

from dsh.sandbox.roots import canonical_path, writable_roots
from dsh.sandbox.vocabulary import SANDBOX_UNAVAILABLE, SandboxUnavailableError


def test_canonical_path_resolves_symlinks_for_an_existing_path():
    directory = tempfile.mkdtemp(prefix="dsh-roots-")
    assert canonical_path(directory) == os.path.realpath(directory)


def test_canonical_path_returns_the_spelling_as_is_when_the_path_cannot_be_resolved():
    assert canonical_path("/does/not/exist/anywhere-xyz") == "/does/not/exist/anywhere-xyz"


def test_read_only_grants_nothing():
    assert writable_roots({"mode": "read-only", "workspaceRoot": os.getcwd()}) == []


def test_workspace_write_grants_the_workspace_root_plus_the_platform_temp_areas():
    workspace = tempfile.mkdtemp(prefix="dsh-ws-")
    roots = writable_roots({"mode": "workspace-write", "workspaceRoot": workspace})
    assert os.path.realpath(workspace) in roots
    assert canonical_path("/tmp") in roots
    assert os.path.realpath(tempfile.gettempdir()) in roots
    # Deduplicated after canonicalization (/tmp and the platform temp may coincide).
    assert len(set(roots)) == len(roots)


def test_sandbox_unavailable_error_carries_the_structured_identity_consumers_key_on():
    error = SandboxUnavailableError("read-only")
    assert error.name == "SandboxUnavailableError"
    assert error.code == SANDBOX_UNAVAILABLE
    assert isinstance(error, Exception)


def test_sandbox_unavailable_error_names_the_refused_mode_and_the_operator_escape_hatches():
    error = SandboxUnavailableError("workspace-write")
    assert '"workspace-write"' in error.message
    assert "danger-full-access" in error.message
    assert "Runner failure" not in error.message


def test_sandbox_unavailable_error_carries_the_runner_detail_discovered_at_execution_time():
    error = SandboxUnavailableError("read-only", "landlock-run: landlock is not enforced by this kernel")
    assert error.code == SANDBOX_UNAVAILABLE
    assert "Runner failure: landlock-run: landlock is not enforced by this kernel" in error.message
