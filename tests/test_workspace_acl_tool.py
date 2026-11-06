from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.shell.workspace_acl_tool import register_workspace_acl_tool


class Recovery:
    def __init__(self):
        self.repairs = []

    def inspect(self, policy, path):
        return dict(diagnosed=True)

    def plan(self, policy, path):
        return self.preview(policy, "bound")

    def preview(self, policy, plan_id):
        return dict(path="E:/projects/workspace", grant="(OI)(CI) Modify", accountSid="S-1-test",
                    outsideWorkspace=False, propagation="inheriting descendants", beforeSddl="D:before")

    def repair(self, policy, plan_id):
        if policy["mode"] == "read-only":
            raise ValueError("read-only")
        self.repairs.append((dict(policy), plan_id))
        return dict(repaired=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["rejected", "cancelled", "unavailable", None, "allowed-once"])
async def test_recovery_requires_exact_approval_without_running_shell(outcome):
    tools = []
    recovery, requests = Recovery(), []
    mode = ["workspace-write"]

    async def approve(request):
        requests.append(request)
        return outcome

    services = dict(tools=SimpleNamespace(register=tools.append),
                    sandbox=SimpleNamespace(acl_recovery=lambda: recovery),
                    sandboxPolicy=SimpleNamespace(resolve=lambda request: dict(mode=mode[0], workspaceRoot="E:/projects/workspace")),
                    approval=SimpleNamespace(request=approve) if outcome is not None else None)
    register_workspace_acl_tool(SimpleNamespace(get=services.get))
    tool = tools[0]
    execution = SimpleNamespace(agent=SimpleNamespace(session=object()), signal=AbortController().signal, callId="call")
    assert await tool["execute"](dict(action="inspect"), execution) == dict(diagnosed=True)
    await tool["execute"](dict(action="plan"), execution)
    if outcome == "allowed-once":
        assert await tool["execute"](dict(action="repair", planId="bound"), execution) == dict(repaired=True)
        assert len(recovery.repairs) == 1
    else:
        with pytest.raises(ValueError):
            await tool["execute"](dict(action="repair", planId="bound"), execution)
        assert not recovery.repairs
    if requests:
        assert requests[0]["callId"] == "call"
        assert "E:/projects/workspace" in requests[0]["reason"] and "D:before" in requests[0]["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["readonly", "cancel", "readonly-during-approval"])
async def test_recovery_rechecks_mode_and_cancellation(change):
    recovery, tools, asks = Recovery(), [], []
    controller = AbortController()
    mode = ["read-only" if change == "readonly" else "workspace-write"]

    async def approve(request):
        asks.append(request)
        if change == "cancel":
            controller.abort("cancelled")
        else:
            mode[0] = "read-only"
        return "allowed-once"

    services = dict(tools=SimpleNamespace(register=tools.append),
                    sandbox=SimpleNamespace(acl_recovery=lambda: recovery),
                    sandboxPolicy=SimpleNamespace(resolve=lambda request: dict(mode=mode[0])),
                    approval=SimpleNamespace(request=approve))
    register_workspace_acl_tool(SimpleNamespace(get=services.get))
    execution = SimpleNamespace(agent=SimpleNamespace(session=object()), signal=controller.signal)
    with pytest.raises(ValueError):
        await tools[0]["execute"](dict(action="repair", planId="bound"), execution)
    assert not recovery.repairs
    assert len(asks) == (0 if change == "readonly" else 1)
