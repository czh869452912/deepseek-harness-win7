import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.interaction.user_approval import UserApprovalService
from dsh.interaction.commands import CommandRegistry


from dsh.core.agent import Agent
from dsh.core.session import Session, SessionStore


@pytest.mark.asyncio
async def test_user_approval_service_policy_and_decision():
    ctx = Context()
    appr = UserApprovalService(ctx)
    session = Session("s1")
    agent = Agent(session=session, ctx=ctx, agent_id="a1")

    # 1. Default policy is 'ask'
    assert appr.effective_policy(session) == "ask"

    # 2. Set policy 'never'
    appr.set_policy(agent, "never")
    assert appr.effective_policy(session) == "never"

    # 3. Inside turn, request with 'never' resolves 'rejected' immediately
    session.append("turn/start", {"turn": 1})
    res_never = await appr.request({"agent": agent, "toolName": "pwsh", "reason": "test action"})
    assert res_never == "rejected"

    # 4. Set policy 'ask'
    appr.set_policy(agent, "ask")
    assert appr.effective_policy(session) == "ask"

    # 5. Interactive decide via waterfall
    def on_request(req, next_fn=None):
        return "allowed-once"

    ctx.on("approval/request", on_request)
    res_grant = await appr.request({"agent": agent, "toolName": "pwsh", "reason": "test action"})
    assert res_grant == "allowed-once"


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
