"""Recovery consumer using the sandbox service and the existing approval channel."""
import json
import os

from dsh.subprocess.local import _signal_aborted


def install_workspace_acl_tool(ctx):
    if os.name != "nt":
        return

    def mount(scope):
        sandbox = scope.get("sandbox")
        if callable(getattr(sandbox, "acl_recovery", None)) and not getattr(sandbox, "runner", None):
            register_workspace_acl_tool(scope)

    ctx.inject(["sandbox", "sandboxPolicy"], mount)


def register_workspace_acl_tool(ctx):
    async def execute(args, execution):
        action = args.get("action")
        if action not in ("inspect", "plan", "repair"):
            raise ValueError("expected workspace_acl action inspect, plan, or repair")
        if _signal_aborted(getattr(execution, "signal", None)):
            raise ValueError("ACL recovery cancelled")
        agent = getattr(execution, "agent", None)
        if agent is None:
            raise ValueError("workspace_acl requires a calling agent and session")
        policy = ctx.get("sandboxPolicy").resolve({"session": getattr(agent, "session", None)})
        recovery = ctx.get("sandbox").acl_recovery()
        if action != "repair":
            if "planId" in args:
                raise ValueError("planId is only valid for repair")
            return getattr(recovery, action)(policy, args.get("path"))
        if "path" in args or not isinstance(args.get("planId"), str):
            raise ValueError("repair requires only the planId of a reviewed plan")
        if policy["mode"] == "read-only":
            raise ValueError("ACL repair is unavailable in read-only mode; change the session mode explicitly")
        plan = recovery.preview(policy, args["planId"])
        approval = ctx.get("approval")
        if approval is None:
            raise ValueError("ACL repair requires approval; no approval service is composed. "
                             "Inspect and plan remain available; use the reviewed plan for external recovery.")
        outcome = await approval.request(dict(agent=agent, toolName="workspace_acl",
            callId=getattr(execution, "callId", None), signal=getattr(execution, "signal", None),
            reason="Repair directory ACL at {}: add {} to account {}. Outside workspace: {}. "
                   "{} Before SDDL: {}".format(plan["path"], plan["grant"], plan["accountSid"],
                       plan["outsideWorkspace"], plan["propagation"], plan["beforeSddl"])))
        if outcome != "allowed-once":
            raise ValueError("ACL repair {}: no permissions changed".format(outcome))
        if _signal_aborted(getattr(execution, "signal", None)):
            raise ValueError("ACL repair cancelled: no permissions changed")
        # Approval can suspend execution; resolve the session again before consuming the bound plan.
        policy = ctx.get("sandboxPolicy").resolve({"session": getattr(agent, "session", None)})
        return recovery.repair(policy, args["planId"])

    ctx.get("tools").register(dict(name="workspace_acl",
        description="Diagnose Windows directory ACLs in the host, even if workspace-write pwsh cannot start. "
            "inspect is read-only and reports the selected directory and ancestors. plan previews an additive "
            "current-account (OI)(CI) Modify grant without writing ACLs; path defaults to the workspace. "
            "Select an ancestor explicitly only when its broader scope is intended. repair takes the planId "
            "and requests user approval for that exact directory and its normal inheritance propagation. "
            "It does not run shell commands, reset ACLs, take ownership, remove Deny entries, or bypass UAC. "
            "After repair, retry the original pwsh call normally; protected descendants need separate review. "
            "If approval is unavailable, report the plan for external recovery; do not bypass the refusal. "
            "After rejected approval, stop and report it; do not request the same repair again without new user authorization.",
        parameters=dict(type="object", additionalProperties=False,
            properties=dict(action=dict(type="string", enum=["inspect", "plan", "repair"]),
                path=dict(type="string", description="Directory for inspect/plan; an ancestor requires an explicit path."),
                planId=dict(type="string", description="Snapshot-bound plan returned by plan; required for repair.")),
            required=["action"]), execute=execute,
        output=dict(schema={"type": "object"}, render=lambda args, value: [
            {"type": "text", "text": json.dumps(value, ensure_ascii=True, indent=2)}])))
