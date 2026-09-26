"""
The sandbox POLICY home (`ctx.sandboxPolicy`): the single owner of the
deployment's sandbox fallbacks plus per-session resolution - the file-effect
`SandboxMode`, the `workspace-write` root, and the override kit (the
`sandbox/mode` event, its fold, and its write path).

1:1 with reference/packages/sandbox/sandbox-policy (src/index.ts and
src/session-mode.ts). Enforcing filesystem, one-shot bash, and terminal backends
read the SAME resolved policy here; before each agent request the owner also
contributes the resolved policy to the cache-safe runtime-context snapshot, and
the agent loop logs that snapshot as model history, so replay reconstructs the
same mode and root the enforcing consumers resolve.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional

from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.sandbox.roots import canonical_path
from dsh.sandbox.vocabulary import (
    CONFINED_SANDBOX_MODES,
    DANGER_FULL_ACCESS,
    READ_ONLY,
    SANDBOX_MODES,
    WORKSPACE_WRITE,
    sandbox_execution_policy,
)

__all__ = [
    "SANDBOX_MODES",
    "SandboxPolicyService",
    "effective_sandbox_mode",
    "render_policy_context",
    "resolve_workspace_root",
    "set_sandbox_mode",
]

def resolve_workspace_root(path: str) -> str:
    """
    Resolve filesystem identity before lexical normalization can erase
    symlink-sensitive components (reference `resolveWorkspaceRoot`).

    @param path: a configured root or a session cwd.
    @returns: the absolute normalized path.
    """
    return os.path.abspath(os.path.normpath(canonical_path(path)))


def effective_sandbox_mode(events: Any) -> Optional[str]:
    """
    The session's sandbox-mode override: the last `sandbox/mode` event in the
    log, or None when the session never switched (callers apply the deployment
    default).

    @param events: session events in log order (other types are skipped).
    @returns: the mode of the last switch event, or None without one.
    """
    log = list(events or [])
    for index in range(len(log) - 1, -1, -1):
        event = log[index]
        if isinstance(event, dict) and event.get("type") == "sandbox/mode":
            return event.get("data", {}).get("mode")
    return None


def set_sandbox_mode(session: Any, mode: str) -> None:
    """
    THE write path for a session's sandbox-mode override: appends exactly one
    `sandbox/mode` event - the switch IS its event.

    @param session: the session the override belongs to.
    @param mode: the mode every subsequent confined call in this session runs
        under, until the next switch.
    """
    session.append("sandbox/mode", {"mode": mode})


def render_policy_context(policy: Any) -> str:
    """
    Render the policy without claiming which capabilities are mounted.

    @param policy: the resolved per-call policy.
    @returns: the exact runtime-context text for that mode.
    """
    mode = policy.get("mode") if isinstance(policy, dict) else policy.mode
    root = policy.get("workspaceRoot") if isinstance(policy, dict) else policy.workspaceRoot
    if mode == READ_ONLY:
        return (
            "Current DSH file policy: read-only. Any available operation enforced by the DSH "
            "file sandbox cannot modify files in the standing mode. Do not refuse a required "
            "modification from this policy alone: try an available tool normally and follow any "
            "denial and escalation guidance it returns."
        )
    if mode == WORKSPACE_WRITE:
        return (
            "Current DSH file policy: workspace-write. Any available operation enforced by the "
            "DSH file sandbox may modify files under the session workspace: "
            + json.dumps(root)
            + ". Some platform temporary areas may also be writable."
        )
    if mode == DANGER_FULL_ACCESS:
        return (
            "Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict "
            "file modifications by available operations."
        )
    raise ValueError("unreachable sandbox mode: {}".format(mode))


class SandboxPolicyService(Service):
    """
    The sandbox-policy service (`ctx.sandboxPolicy`).

    Owns the deployment default mode, the fallback workspace root, and the
    per-call resolution every enforcing capability reads. Mounted by the
    installation row `@deepseek-ai/dsh-sandbox-policy`.
    """

    #: Inline schema: the config catalog walks `Config` statically, so the
    #: closed mode union is validated when the row loads.
    Config = Schema.object(
        {
            "mode": Schema.union(READ_ONLY, WORKSPACE_WRITE, DANGER_FULL_ACCESS).default(READ_ONLY),
            # No schema default: the process cwd is resolved in the constructor
            # so the stored root is always absolute regardless of how supplied.
            "workspaceRoot": Schema.string(),
        }
    )

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, "sandboxPolicy")
        cfg = config or {}
        #: The deployment default mode - the fallback beneath a session override.
        self.defaultMode = cfg.get("mode") or READ_ONLY
        #: The absolute `workspace-write` fallback root for calls without a cwd.
        self.workspaceRoot = resolve_workspace_root(cfg.get("workspaceRoot") or os.getcwd())
        self._contribute_policy_context(ctx)

    def apply(self, ctx: Any = None, config: Any = None) -> None:
        """The service mounts from its constructor; apply keeps the plugin shape."""
        return None

    def _contribute_policy_context(self, ctx: Any) -> None:
        """
        Contribute the resolved policy to the cache-safe runtime-context
        snapshot, through dependency inversion on `systemPrompt` (the reference
        registers the contribution from `ctx.inject(['systemPrompt'], ...)`, so
        the contribution is owned by the injecting fiber).
        """
        if ctx is None or not hasattr(ctx, "inject"):
            return

        def contribute(scope: Any) -> None:
            prompt = scope.get("systemPrompt") if hasattr(scope, "get") else None
            if prompt is None or not hasattr(prompt, "context"):
                return
            prompt.context(
                {
                    "name": "sandbox:policy",
                    "order": 110,
                    "text": self._policy_context_text,
                }
            )

        ctx.inject(["systemPrompt"], contribute)

    def _policy_context_text(self, context: Any) -> str:
        """Render the caller's resolved policy, or nothing without an agent."""
        agent = context.get("agent") if isinstance(context, dict) else getattr(context, "agent", None)
        session = getattr(agent, "session", None) if agent is not None else None
        if session is None:
            return ""
        return render_policy_context(self.resolve({"session": session}))

    def resolve(self, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Resolve the complete policy for one capability call.

        An approved explicit mode outranks the session's last `sandbox/mode`
        event, which outranks the deployment default. A session cwd is its
        `workspace-write` boundary; the configured root is the fallback for
        agentless calls and sessions without a cwd.

        @param request: optional `session` and approved `mode` override.
        @returns: the fully resolved per-call mode and absolute workspace root.
        """
        req = request or {}
        session = req.get("session")
        mode = req.get("mode")
        if mode is None and session is not None:
            mode = self.override_of(session)
        if mode is None:
            mode = self.defaultMode
        cwd = None
        if session is not None:
            header = getattr(session, "header", None)
            cwd = getattr(header, "cwd", None) if header is not None else None
        root = resolve_workspace_root(cwd if cwd is not None else self.workspaceRoot)
        session_id = getattr(session, "id", None) if session is not None else None
        return sandbox_execution_policy(mode, root, session_id)

    def override_of(self, session: Any) -> Optional[str]:
        """
        Read the session override without applying the deployment default.

        @param session: session whose log supplies the override.
        @returns: the last logged mode, or None without one.
        """
        return effective_sandbox_mode(getattr(session, "events", None))
