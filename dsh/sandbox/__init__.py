"""
Sandbox capability package: the file-effect policy vocabulary every enforcing
backend shares (`@deepseek-ai/dsh-sandbox`), the policy home
(`@deepseek-ai/dsh-sandbox-policy`), and the policy's invariant companion.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from dsh.sandbox.roots import canonical_path, writable_roots
from dsh.sandbox.sandbox_policy import (
    SandboxPolicyService,
    effective_sandbox_mode,
    render_policy_context,
    resolve_workspace_root,
    set_sandbox_mode,
)
from dsh.sandbox.vocabulary import (
    CONFINED_SANDBOX_MODES,
    DANGER_FULL_ACCESS,
    READ_ONLY,
    SANDBOX_MODES,
    SANDBOX_UNAVAILABLE,
    WORKSPACE_WRITE,
    SandboxUnavailableError,
    policy_mode,
    policy_session_id,
    policy_workspace_root,
    sandbox_execution_policy,
)

__all__ = [
    "CONFINED_SANDBOX_MODES",
    "DANGER_FULL_ACCESS",
    "READ_ONLY",
    "SANDBOX_MODES",
    "SANDBOX_UNAVAILABLE",
    "WORKSPACE_WRITE",
    "SandboxPolicyService",
    "SandboxUnavailableError",
    "canonical_path",
    "effective_sandbox_mode",
    "policy_mode",
    "policy_session_id",
    "policy_workspace_root",
    "render_policy_context",
    "resolve_workspace_root",
    "sandbox_execution_policy",
    "set_sandbox_mode",
    "writable_roots",
]