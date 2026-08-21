import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.interaction.user_approval import UserApprovalService
from dsh.interaction.commands import CommandRegistry


@pytest.mark.asyncio
async def test_user_approval_service_policy_and_decision():
    ctx = Context()
    appr = UserApprovalService(ctx, policy="always")
    assert await appr.request_approval("run_command") is True

    appr.set_policy("never")
    assert await appr.request_approval("run_command") is False

    appr.set_policy("ask")
    requested_event = []

    def on_requested(data):
        requested_event.append(data)
        # Auto decide in background
        appr.decide(data["requestId"], True)

    ctx.on("approval/requested", on_requested)

    res = await appr.request_approval("delete_file", {"path": "test.txt"}, timeout_s=5.0)
    assert res is True
    assert len(requested_event) == 1
    assert requested_event[0]["action"] == "delete_file"


@pytest.mark.asyncio
async def test_command_registry_execution():
    ctx = Context()
    cmds = CommandRegistry(ctx)

    def handle_compact(args):
        return f"Compacted with args: {args}"

    cmds.register("/compact", "Compact conversation", handle_compact)

    res = await cmds.execute("/compact --force")
    assert res == "Compacted with args: --force"

    res_none = await cmds.execute("not a command")
    assert res_none is None
