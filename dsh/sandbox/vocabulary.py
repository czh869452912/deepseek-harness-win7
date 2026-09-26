"""
Sandbox capability vocabulary: the file-effect mode union and the complete
per-call execution policy.

1:1 with reference/packages/sandbox/sandbox/src/index.ts: `SandboxMode` is the
closed three-way file-effect vocabulary, `ConfinedSandboxMode` is the confining
half, and `SandboxExecutionPolicy` is the policy resolved for one capability
call (mode plus the absolute `workspace-write` root, and the calling session's
opaque id when there is one). The service-definition half of that package (the
`SandboxProvider` service and the confinement/runner-failure vocabulary) belongs
to the sandbox backends and lands with them.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, Optional

from dsh.llm.error import HarnessError

__all__ = [
    "DANGER_FULL_ACCESS",
    "WORKSPACE_WRITE",
    "READ_ONLY",
    "SANDBOX_MODES",
    "CONFINED_SANDBOX_MODES",
    "SANDBOX_UNAVAILABLE",
    "SandboxUnavailableError",
    "sandbox_execution_policy",
    "policy_mode",
    "policy_workspace_root",
    "policy_session_id",
]

#: File-effect policy modes for confined processes.
READ_ONLY = "read-only"
WORKSPACE_WRITE = "workspace-write"
DANGER_FULL_ACCESS = "danger-full-access"

#: Every mode, in the reference's declaration order.
SANDBOX_MODES = [READ_ONLY, WORKSPACE_WRITE, DANGER_FULL_ACCESS]

#: The confining (non-`danger-full-access`) modes a `SandboxPolicy` can carry.
CONFINED_SANDBOX_MODES = [READ_ONLY, WORKSPACE_WRITE]

#: Error code a provider raises when no backend can enforce the requested mode.
SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"


class SandboxUnavailableError(HarnessError):
    """
    Thrown when a provider cannot enforce the requested mode.

    Carries {@link SANDBOX_UNAVAILABLE} through the structured error channel so
    callers can distinguish missing confinement from command failure; the
    runner's own first stderr line rides along as `detail` when the failure is
    discovered at execution time.
    """

    def __init__(self, mode: str, detail: Optional[str] = None):
        message = (
            'sandbox mode "{0}" is requested but no sandbox backend is usable on this host; '
            "refusing to run the command unconfined. Install bubblewrap or run a Landlock-enforcing "
            "kernel (Linux), ensure sandbox-exec is usable (macOS), or ensure the ACL "
            "restricted-token runner can start (Windows) \u2014 otherwise switch the consumer to "
            "danger-full-access."
        ).format(mode) + ("" if detail is None else " Runner failure: {}".format(detail))
        super().__init__(message, SANDBOX_UNAVAILABLE)
        self.name = "SandboxUnavailableError"


def sandbox_execution_policy(
    mode: str,
    workspace_root: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the complete file-effect policy resolved for one capability call.

    The reference resolves the policy as an object literal; the port carries the
    same fields under the same names, with `sessionId` present only when a
    calling session exists (`exactOptionalPropertyTypes`).

    @param mode: the file-effect mode this execution runs under.
    @param workspace_root: the absolute root `workspace-write` may write under.
    @param session_id: opaque identity of the calling session, when there is one.
    @returns: the resolved policy.
    """
    policy: Dict[str, Any] = {"mode": mode, "workspaceRoot": workspace_root}
    if session_id is not None:
        policy["sessionId"] = session_id
    return policy


def policy_mode(policy: Any) -> str:
    """Read the mode of a resolved policy (mapping or attribute carrier)."""
    if isinstance(policy, dict):
        return policy["mode"]
    return policy.mode


def policy_workspace_root(policy: Any) -> str:
    """Read the absolute workspace root of a resolved policy."""
    if isinstance(policy, dict):
        return policy["workspaceRoot"]
    return policy.workspaceRoot


def policy_session_id(policy: Any) -> Optional[str]:
    """Read the calling session's opaque id, absent for agentless calls."""
    if isinstance(policy, dict):
        return policy.get("sessionId")
    return getattr(policy, "sessionId", None)
