"""
1:1 parity suite for `@deepseek-ai/dsh-sandbox-policy`
(`dsh/sandbox/sandbox_policy.py`).

Upstream is reference/packages/sandbox/sandbox-policy/tests/policy.spec.ts: the
deployment default the service exposes (mode plus `workspaceRoot`), the per-call
resolution that pairs a session's `sandbox/mode` override with its immutable cwd,
the `sandbox:policy` request context, and the `sandbox/mode` session kit
(fold + write path).

Platform notes:
- the upstream `it.skipIf(process.platform === 'win32')` case for POSIX
  component semantics of a symlinked cwd is carried as the same conditional
  skip;
- session cwds are spelled with the host's absolute convention because
  `session header cwd must be an absolute path` (the reference's
  `path.isAbsolute` accepts a root-relative POSIX spelling on Windows, while
  `os.path.isabs` in Python 3.8 does not) - the assertions are unchanged.
"""

import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from dsh.core.session import Session, SessionStore
from dsh.core.system_prompt import SystemPrompt, render_context_snapshot, render_prompt
from dsh.cordis.context import Context
from dsh.sandbox.sandbox_policy import (
    SANDBOX_MODES,
    SandboxPolicyService,
    effective_sandbox_mode,
    set_sandbox_mode,
)

VOLUME_ROOT = os.path.abspath(os.sep)


def absolute(*parts: str) -> str:
    """An absolute path in the host's convention, normalized like `resolve()`."""
    return os.path.abspath(os.path.normpath(os.path.join(VOLUME_ROOT, *parts)))


async def mounted(config: Optional[Dict[str, Any]] = None) -> Context:
    ctx = Context()
    await ctx.plugin(SandboxPolicyService, config)
    return ctx


def session(session_id: str, cwd: Optional[str] = None) -> Session:
    header: Dict[str, Any] = {"version": 0, "id": session_id, "createdAt": 0}
    if cwd is not None:
        header["cwd"] = cwd
    return Session.create(session_id, None, header)


def agent_for(active_session: Session) -> Any:
    return SimpleNamespace(session=active_session)


async def policy_context(ctx: Context, active_session: Session) -> Optional[str]:
    assembly = await ctx.systemPrompt.assemble({"agent": agent_for(active_session)})
    for context in assembly["contexts"]:
        if context["name"] == "sandbox:policy":
            return context["text"]
    return None


@pytest.mark.asyncio
async def test_defaults_to_read_only_under_the_process_cwd():
    ctx = await mounted()
    assert ctx.sandboxPolicy.defaultMode == "read-only"
    assert ctx.sandboxPolicy.workspaceRoot == os.path.abspath(os.path.normpath(os.getcwd()))


@pytest.mark.asyncio
async def test_carries_a_configured_mode_and_resolves_the_workspace_root_absolute():
    ctx = await mounted({"mode": "workspace-write", "workspaceRoot": os.path.join(VOLUME_ROOT, "ws", "..", "ws", ".", "sub")})
    assert ctx.sandboxPolicy.defaultMode == "workspace-write"
    assert ctx.sandboxPolicy.workspaceRoot == absolute("ws", "sub")


@pytest.mark.asyncio
async def test_resolves_the_deployment_policy_for_an_agentless_call():
    ctx = await mounted({"mode": "workspace-write", "workspaceRoot": absolute("fallback")})
    assert ctx.sandboxPolicy.resolve() == {
        "mode": "workspace-write",
        "workspaceRoot": absolute("fallback"),
    }


@pytest.mark.asyncio
async def test_resolves_each_session_mode_and_cwd_together_without_changing_the_fallback():
    ctx = await mounted({"mode": "workspace-write", "workspaceRoot": absolute("fallback")})
    first = session("sess-first", absolute("projects", "first"))
    second = session("sess-second", absolute("projects", "second"))
    set_sandbox_mode(second, "read-only")

    assert ctx.sandboxPolicy.resolve({"session": first}) == {
        "mode": "workspace-write",
        "workspaceRoot": absolute("projects", "first"),
        "sessionId": "sess-first",
    }
    assert ctx.sandboxPolicy.resolve({"session": second}) == {
        "mode": "read-only",
        "workspaceRoot": absolute("projects", "second"),
        "sessionId": "sess-second",
    }
    assert ctx.sandboxPolicy.override_of(first) is None
    assert ctx.sandboxPolicy.override_of(second) == "read-only"
    assert ctx.sandboxPolicy.resolve() == {
        "mode": "workspace-write",
        "workspaceRoot": absolute("fallback"),
    }


@pytest.mark.skipif(sys.platform == "win32", reason="upstream skips this case on win32; POSIX component semantics")
@pytest.mark.asyncio
async def test_resolves_a_symlink_sensitive_session_cwd_with_posix_component_semantics(tmp_path):
    lexical = tmp_path / "lexical"
    physical = tmp_path / "physical"
    child = physical / "child"
    lexical.mkdir()
    child.mkdir(parents=True)
    link = lexical / "link"
    link.symlink_to(child, target_is_directory=True)
    cwd = str(link) + os.sep + ".."
    ctx = await mounted({"mode": "workspace-write", "workspaceRoot": absolute("fallback")})

    assert ctx.sandboxPolicy.resolve({"session": session("sess-symlink-parent", cwd)}) == {
        "mode": "workspace-write",
        "workspaceRoot": os.path.realpath(str(physical)),
        "sessionId": "sess-symlink-parent",
    }


@pytest.mark.asyncio
async def test_lets_an_approved_mode_outrank_the_session_mode_while_retaining_its_root():
    ctx = await mounted({"workspaceRoot": absolute("fallback")})
    active = session("sess-approved", absolute("projects", "approved"))
    set_sandbox_mode(active, "read-only")
    assert ctx.sandboxPolicy.resolve({"session": active, "mode": "danger-full-access"}) == {
        "mode": "danger-full-access",
        "workspaceRoot": absolute("projects", "approved"),
        "sessionId": "sess-approved",
    }


@pytest.mark.asyncio
async def test_uses_the_configured_root_when_a_session_has_no_cwd():
    ctx = await mounted({"workspaceRoot": absolute("fallback")})
    assert ctx.sandboxPolicy.resolve({"session": session("sess-no-cwd")})["workspaceRoot"] == absolute("fallback")


@pytest.mark.asyncio
async def test_rejects_a_mode_outside_the_closed_vocabulary_at_load():
    ctx = Context()
    # schemastery rejects the union violation when the plugin loads.
    with pytest.raises(Exception):
        await ctx.plugin(SandboxPolicyService, {"mode": "yolo"})


@pytest.mark.asyncio
async def test_disposes_the_service_and_context_contribution_from_a_child_fiber():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    fiber = await ctx.plugin(SandboxPolicyService, {})
    assert ctx.get("sandboxPolicy") is not None
    assert "read-only" in (await policy_context(ctx, session("sess-hmr")))
    await fiber.dispose()
    assert ctx.get("sandboxPolicy") is None
    assembly = await ctx.systemPrompt.assemble()
    assert [c for c in assembly["contexts"] if c["name"] == "sandbox:policy"] == []


async def prompt_mounted(config: Optional[Dict[str, Any]] = None) -> Context:
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(SandboxPolicyService, config)
    return ctx


POLICY_TEXTS = {
    "read-only": (
        "Current DSH file policy: read-only. Any available operation enforced by the DSH file "
        "sandbox cannot modify files in the standing mode. Do not refuse a required modification "
        "from this policy alone: try an available tool normally and follow any denial and "
        "escalation guidance it returns."
    ),
    "danger-full-access": (
        "Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict file "
        "modifications by available operations."
    ),
}


@pytest.mark.parametrize("mode", ["read-only", "workspace-write", "danger-full-access"])
@pytest.mark.asyncio
async def test_renders_the_exact_policy_without_a_capability_inventory(mode):
    ctx = await prompt_mounted({"mode": mode, "workspaceRoot": absolute("fallback")})
    workspace_root = absolute("projects", "current")
    if mode == "workspace-write":
        expected = (
            "Current DSH file policy: workspace-write. Any available operation enforced by the DSH "
            "file sandbox may modify files under the session workspace: "
            + _json(workspace_root)
            + ". Some platform temporary areas may also be writable."
        )
    else:
        expected = POLICY_TEXTS[mode]

    active = session("sess-{}".format(mode), os.path.join(VOLUME_ROOT, "projects", "..", "projects", "current"))
    assert await policy_context(ctx, active) == expected


def _json(value: str) -> str:
    """`JSON.stringify` of one path, as the reference renders it."""
    import json

    return json.dumps(value)


@pytest.mark.asyncio
async def test_keeps_the_complete_rendered_prompt_byte_stable_across_temporary_directory_changes(monkeypatch):
    ctx = await prompt_mounted({"mode": "workspace-write"})
    active = session("sess-tmpdir-stability", absolute("projects", "current"))
    previous = os.environ.get("TMPDIR")
    try:
        os.environ["TMPDIR"] = os.path.join(VOLUME_ROOT, "tmp", "first-host-temp")
        first_assembly = await ctx.systemPrompt.assemble({"agent": agent_for(active)})
        first_prompt = render_prompt(first_assembly)
        first_context = render_context_snapshot(first_assembly)
        os.environ["TMPDIR"] = os.path.join(VOLUME_ROOT, "tmp", "second-host-temp")
        second_assembly = await ctx.systemPrompt.assemble({"agent": agent_for(active)})
        assert render_prompt(second_assembly) == first_prompt
        assert render_context_snapshot(second_assembly) == first_context
        assert "host-temp" not in first_context
    finally:
        if previous is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous


@pytest.mark.asyncio
async def test_reflects_the_latest_durable_switch_on_the_next_assembly_and_stays_byte_stable_otherwise():
    ctx = await prompt_mounted()
    active = session("sess-switch", absolute("projects", "current"))
    first = await policy_context(ctx, active)
    assert await policy_context(ctx, active) == first

    set_sandbox_mode(active, "danger-full-access")
    danger = await policy_context(ctx, active)
    assert danger == POLICY_TEXTS["danger-full-access"]
    assert await policy_context(ctx, active) == danger

    set_sandbox_mode(active, "workspace-write")
    assert await policy_context(ctx, active) == (
        "Current DSH file policy: workspace-write. Any available operation enforced by the DSH file "
        "sandbox may modify files under the session workspace: "
        + _json(absolute("projects", "current"))
        + ". Some platform temporary areas may also be writable."
    )


@pytest.mark.asyncio
async def test_reconstructs_resumed_policy_from_the_session_log_and_omits_diagnostics_without_an_agent():
    active = session("sess-resume", absolute("projects", "current"))
    set_sandbox_mode(active, "workspace-write")
    resumed = Session.create(active.id, list(active.events), active.header)
    ctx = await prompt_mounted({"mode": "read-only"})

    assert "workspace-write" in (await policy_context(ctx, resumed))
    assembly = await ctx.systemPrompt.assemble()
    assert [c for c in assembly["contexts"] if c["name"] == "sandbox:policy"][0]["text"] == ""


def test_sandbox_modes_lists_every_mode_for_advertisement_and_validation():
    assert SANDBOX_MODES == ["read-only", "workspace-write", "danger-full-access"]


def test_effective_sandbox_mode_folds_to_the_last_switch_or_none_without_one():
    log = Session.create("sess-fold")
    assert effective_sandbox_mode(log.events) is None
    set_sandbox_mode(log, "workspace-write")
    set_sandbox_mode(log, "read-only")
    assert effective_sandbox_mode(log.events) == "read-only"


def test_set_sandbox_mode_appends_exactly_one_event_per_switch():
    log = Session.create("sess-write")
    set_sandbox_mode(log, "danger-full-access")
    mode_events = [e for e in log.events if e["type"] == "sandbox/mode"]
    assert len(mode_events) == 1
    assert mode_events[0]["data"] == {"mode": "danger-full-access"}
