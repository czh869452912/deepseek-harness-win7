import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.interaction.user_approval import UserApprovalService
from dsh.interaction.commands import CommandsPlugin
from dsh.core.abort import AbortController
from dsh.core.scope import create_scope


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
    """
    The registry registers the canonical `CommandDefinition` and executes a
    resolved line against the exact receiving agent
    (`reference/packages/interaction/commands/src/index.ts`).
    """
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(CommandsPlugin)

    seen = []

    def handle_compact(invocation):
        seen.append(invocation)
        return {"kind": "success", "text": f"Compacted with args: {invocation.rawInput.strip()}"}

    ctx.commands.register({
        "name": "compact",
        "description": "Compact conversation",
        "handler": handle_compact,
    })

    session = ctx.get("sessions").create("compact-session")
    agent = Agent(session=session, ctx=ctx, agent_id="compact-session")

    execution = await ctx.commands.execute(
        agent, "/compact --force", [], AbortController().signal
    )
    assert dict(execution.result) == {"kind": "success", "text": "Compacted with args: --force"}
    assert seen[0].rawInput == " --force"

    assert await ctx.commands.execute(agent, "not a command", [], AbortController().signal) is None
