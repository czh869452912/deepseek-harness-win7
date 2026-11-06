"""Actual host recovery while the workspace's confined shell is unavailable."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.sandbox.windows_acl import capability_sid
from dsh.sandbox.windows_acl_recovery import WindowsAclRecovery
from test_windows_acl_materialization import owned_acl, run


pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows ACL recovery")


def policy(folder, session="owner"):
    return dict(mode="workspace-write", workspaceRoot=str(folder), sessionId=session)


def remove_backup(result):
    path = Path(result["backup"])
    path.unlink()
    path.parent.rmdir()


@pytest.mark.parametrize("layout", ["this-folder", "capability-only"])
def test_repair_then_real_restricted_nested_read_write_without_restart(owned_acl, layout):
    api, folder, account, install, snapshot = owned_acl
    workspace, private = folder / "workspace", folder / "private"
    workspace.mkdir()
    private.mkdir()
    sddl = "D:P(A;;FA;;;USER)"
    if layout == "capability-only":
        sddl = "D:P(A;OICI;0x110156;;;" + capability_sid(str(workspace)) + ")"
    install(workspace, sddl)
    recovery, spec = WindowsAclRecovery(api), policy(workspace)
    before = snapshot(workspace)
    report = recovery.inspect(spec)
    assert report["directories"][0]["ready"] is False
    assert snapshot(workspace) == before
    plan = recovery.plan(spec)
    assert plan["accountSid"] == account and not plan["outsideWorkspace"]
    assert snapshot(workspace) == before
    result = recovery.repair(spec, plan["planId"])
    try:
        backup = json.loads(Path(result["backup"]).read_text(encoding="utf-8"))
        assert backup["beforeSddl"] == plan["beforeSddl"]
        assert result["workspaceReady"]
        assert snapshot(workspace).control & 0x1000 == before.control & 0x1000
        payload = ("from pathlib import Path; p=Path('a/b'); p.mkdir(parents=True); "
                   "f=p/'converted.md'; f.write_text('# converted',encoding='utf-8'); "
                   "assert f.read_text(encoding='utf-8')=='# converted'; f.unlink(); "
                   "p.rmdir(); p.parent.rmdir(); print('RECOVERED')")
        execution = run(workspace, private, payload)
        assert execution.returncode == 0, execution.stderr
        assert "RECOVERED" in execution.stdout
        with pytest.raises(ValueError, match="missing"):
            recovery.repair(spec, plan["planId"])
    finally:
        remove_backup(result)


def test_explicit_parent_plan_propagates_but_preserves_protected_descendant(owned_acl):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, "D:P(A;;FA;;;USER)")
    workspace = folder / "workspace"
    workspace.mkdir()
    protected = workspace / "protected"
    protected.mkdir()
    install(protected, "D:P(A;;FA;;;USER)")
    held = snapshot(protected)
    recovery, spec = WindowsAclRecovery(api), policy(workspace)
    default = recovery.plan(spec)
    assert default["path"] == os.path.normcase(str(workspace))
    parent = recovery.plan(spec, str(folder))
    assert parent["outsideWorkspace"]
    assert "other workspaces" in parent["propagation"]
    result = recovery.repair(spec, parent["planId"])
    try:
        assert result["workspaceReady"]
        assert snapshot(protected) == held
        assert not recovery.inspect(spec, str(protected))["directories"][0]["ready"]
    finally:
        remove_backup(result)


def test_parent_repair_reports_remaining_protected_workspace(owned_acl):
    api, folder, _account, install, snapshot = owned_acl
    workspace = folder / "workspace"
    workspace.mkdir()
    install(folder, "D:P(A;;FA;;;USER)")
    install(workspace, "D:P(A;;FA;;;USER)")
    recovery, spec = WindowsAclRecovery(api), policy(workspace)
    before = snapshot(workspace)
    plan = recovery.plan(spec, str(folder))
    result = recovery.repair(spec, plan["planId"])
    try:
        assert not result["workspaceReady"]
        assert snapshot(workspace) == before
        local_plan = recovery.plan(spec)
        local_result = recovery.repair(spec, local_plan["planId"])
        try:
            assert local_result["workspaceReady"]
        finally:
            remove_backup(local_result)
    finally:
        remove_backup(result)


def test_backup_failure_does_not_apply_permissions(owned_acl, monkeypatch):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, "D:P(A;;FA;;;USER)")
    recovery, spec = WindowsAclRecovery(api), policy(folder)
    plan = recovery.plan(spec)
    before = snapshot(folder)
    backup_dir = folder.parent / "failed-backup"

    def mkdir(**_kwargs):
        backup_dir.mkdir()
        return str(backup_dir)

    def fail(_fd):
        raise OSError("injected backup failure")

    monkeypatch.setattr("dsh.sandbox.windows_acl_recovery.tempfile.mkdtemp", mkdir)
    monkeypatch.setattr("dsh.sandbox.windows_acl_recovery.os.fsync", fail)
    with pytest.raises(OSError, match="backup failure"):
        recovery.repair(spec, plan["planId"])
    assert snapshot(folder) == before
    (backup_dir / "directory-acl.json").unlink()
    backup_dir.rmdir()


def test_reparse_directory_is_not_a_repair_target(owned_acl):
    import subprocess

    api, folder, _account, _install, snapshot = owned_acl
    target, junction = folder / "target", folder / "junction"
    target.mkdir()
    created = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)],
                             capture_output=True, timeout=10)
    assert created.returncode == 0, created.stderr
    before = snapshot(target)
    try:
        recovery = WindowsAclRecovery(api)
        with pytest.raises(ValueError, match="reparse"):
            recovery.plan(policy(folder), str(junction))
        assert snapshot(target) == before
    finally:
        junction.rmdir()


@pytest.mark.parametrize("change", ["acl", "identity", "expiry", "session", "readonly"])
def test_stale_or_wrong_context_plan_never_applies(owned_acl, change):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, "D:P(A;;FA;;;USER)")
    recovery, spec = WindowsAclRecovery(api), policy(folder)
    plan = recovery.plan(spec)
    if change == "acl":
        install(folder, "D:P(A;;FA;;;USER)(A;;FR;;;AU)")
    elif change == "identity":
        held = folder.parent / "held"
        folder.rename(held)
        folder.mkdir()
        install(folder, "D:P(A;;FA;;;USER)")
    elif change == "expiry":
        recovery.plans[plan["planId"]]["expires"] = 0
    elif change == "session":
        spec["sessionId"] = "other"
    else:
        spec["mode"] = "read-only"
    before = snapshot(folder)
    try:
        with pytest.raises(ValueError):
            recovery.repair(spec, plan["planId"])
        assert snapshot(folder) == before
    finally:
        if change == "identity":
            folder.rmdir()
            held.rename(folder)


@pytest.mark.parametrize("layout", ["D:PNO_ACCESS_CONTROL", "D:P", "D:P(D;OICI;FR;;;USER)(A;;FA;;;USER)"])
def test_diagnosis_survives_nonrepairable_acl_and_does_not_mutate(owned_acl, layout):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, layout)
    recovery, spec = WindowsAclRecovery(api), policy(folder)
    before = snapshot(folder)
    item = recovery.inspect(spec)["directories"][0]
    assert item["ready"] is False and "sddl" in item
    with pytest.raises((ValueError, OSError)):
        recovery.plan(spec)
    assert snapshot(folder) == before


def test_refuses_unrelated_and_drive_scope(owned_acl):
    api, folder, _account, _install, _snapshot = owned_acl
    recovery, spec = WindowsAclRecovery(api), policy(folder)
    with pytest.raises(ValueError, match="ancestor"):
        recovery.inspect(spec, str(folder.parent / "sibling"))
    with pytest.raises(ValueError, match="drive"):
        recovery.plan(spec, folder.anchor)


def test_recovery_preserves_capability_deny_with_original_workspace_path_spelling(owned_acl):
    api, folder, _account, install, snapshot = owned_acl
    original = str(folder).upper()
    sid = capability_sid(original)
    install(folder, "D:P(D;OICI;0x110156;;;" + sid + ")(A;;FA;;;USER)")
    before = snapshot(folder)
    recovery = WindowsAclRecovery(api)
    spec = policy(original)
    assert not recovery.inspect(spec)["directories"][0]["ready"]
    with pytest.raises(ValueError, match="cannot resolve"):
        recovery.plan(spec)
    assert snapshot(folder) == before


def test_post_apply_failure_keeps_backup_and_never_claims_success(owned_acl, monkeypatch):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, "D:P(A;;FA;;;USER)")
    recovery, spec = WindowsAclRecovery(api), policy(folder)
    plan = recovery.plan(spec)
    before = snapshot(folder)
    # An API success without the promised grant must not be reported as repaired.
    monkeypatch.setattr(recovery.guard, "SetSecurityInfo", lambda *_: 0)
    with pytest.raises(OSError, match="no automatic rollback") as error:
        recovery.repair(spec, plan["planId"])
    assert snapshot(folder) == before
    backup = str(error.value).split("Backup: ", 1)[1].split(". ", 1)[0]
    assert Path(backup).is_file()
    remove_backup(dict(backup=backup))


@pytest.mark.asyncio
async def test_persistent_tool_blocked_diagnose_approve_repair_and_resume(owned_acl):
    from dsh.core.abort import AbortController
    from dsh.core.scope import scope_of
    from dsh.sandbox.local import LocalSandboxProvider
    from dsh.sandbox.sandbox_policy import SandboxPolicyService
    from dsh.sandbox.vocabulary import SandboxUnavailableError
    from dsh.subprocess.local import LocalSubprocessRuntime
    from dsh.terminal.local import LocalTerminalPlugin
    from dsh.terminal.service import TerminalSessionService
    from dsh.terminal.persistent_pwsh import PersistentPwshPlugin
    from test_subagent_in_process import setup

    api, folder, _account, install, snapshot = owned_acl
    install(folder, "D:P(A;;FA;;;USER)")
    ctx, _, owner = await setup()
    await owner.dispose()
    owner = await ctx.get("agent_loop").create("acl-owner", {"cwd": str(folder)})
    execution = SimpleNamespace(agent=owner.agent, signal=AbortController().signal, callId="acl-recovery")
    outcome, approvals, result = ["rejected"], [], None

    async def approve(request):
        approvals.append(request)
        return outcome[0]

    ctx.set_service("approval", SimpleNamespace(request=approve))
    try:
        await ctx.plugin(LocalSubprocessRuntime)
        await ctx.plugin(LocalSandboxProvider)
        ctx.get("sandbox").api = api
        await ctx.plugin(SandboxPolicyService, dict(mode="workspace-write", workspaceRoot=str(folder)))
        await ctx.plugin(TerminalSessionService)
        await ctx.plugin(LocalTerminalPlugin, dict(shellDialect="pwsh", idleSilenceMs=150,
                                                  pollIntervalMs=10, timeoutMs=10000))
        fiber = await ctx.plugin(PersistentPwshPlugin, dict(timeoutMs=10000))
        tools = ctx.get("tools")
        pwsh = tools.get("pwsh", scope_of(owner.agent.ctx))
        acl = tools.get("workspace_acl", scope_of(owner.agent.ctx))
        assert acl is not None
        with pytest.raises(SandboxUnavailableError, match="workspace_acl inspect"):
            await pwsh.execute(dict(command="Write-Output 'never-ran'"), execution)
        assert not ctx.get("terminals").list(owner.agent)
        before = snapshot(folder)
        report = await acl.execute(dict(action="inspect"), execution)
        assert report["directories"][0]["ready"] is False
        plan = await acl.execute(dict(action="plan"), execution)
        with pytest.raises(ValueError, match="rejected"):
            await acl.execute(dict(action="repair", planId=plan["planId"]), execution)
        assert snapshot(folder) == before
        assert approvals[0]["toolName"] == "workspace_acl"
        assert str(folder).lower() in approvals[0]["reason"]
        outcome[0] = "allowed-once"
        result = await acl.execute(dict(action="repair", planId=plan["planId"]), execution)
        assert result["workspaceReady"]
        output = await pwsh.execute(dict(command="New-Item -ItemType Directory -Path 'converted' | Out-Null; "
            "Set-Content -LiteralPath 'converted/result.md' -Value '# recovered'; "
            "Get-Content -LiteralPath 'converted/result.md'"), execution)
        assert "# recovered" in output
        assert "# recovered" in (folder / "converted/result.md").read_text(encoding="utf-8-sig")
        await fiber.dispose()
        assert tools.get("workspace_acl", scope_of(owner.agent.ctx)) is None
    finally:
        await owner.dispose()
        await ctx.fiber.dispose()
        if result:
            remove_backup(result)


@pytest.mark.asyncio
async def test_actual_web_preset_scopes_expose_host_diagnosis(owned_acl):
    from canonical_web_fixture import web_context, close_web_context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.tools import ToolExecutionInput

    _api, folder, _account, install, snapshot = owned_acl
    home = folder.parent / "web-home"
    install(folder, "D:P(A;;FA;;;USER)")
    before = snapshot(folder)
    ctx = await web_context(home)
    try:
        for preset in ("minimal", "standard"):
            session_id = "acl-" + preset
            await ctx.get("sessionController").create(dict(sessionId=session_id, cwd=str(folder), agentPreset=preset))
            agent = ctx.get("agents").get(session_id)
            agent.session.append("sandbox/mode", dict(mode="workspace-write"))
            tools = ctx.get("tools")
            assert "workspace_acl" in [item["name"] for item in tools.schemas(agent)]
            result = await tools.execute(ToolExecutionInput("acl-diagnose-" + preset, "workspace_acl",
                dict(action="inspect"), agent=agent, signal=NEVER_ABORTED))
            assert not result.is_error, result.content
            assert result.value["directories"][0]["ready"] is False
            assert snapshot(folder) == before
    finally:
        await close_web_context(ctx)
