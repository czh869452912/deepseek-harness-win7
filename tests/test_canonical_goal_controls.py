import pytest

from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolRunContext, ToolExecutionInput
from dsh.goal.service import GoalService, GoalError
from dsh.goal.fold import goal_ref
from dsh.goal.tools import CanonicalToolGoal
from dsh.goal.command import CommandGoal
from dsh.interaction.commands import CommandsPlugin, CommandInvocation


async def setup():
    ctx = Context()
    for plugin in (SessionPlugin, AgentPlugin, ToolsPlugin, SystemPrompt, GoalService, CommandsPlugin):
        await ctx.plugin(plugin)
    controls = await ctx.plugin(CanonicalToolGoal)
    command = await ctx.plugin(CommandGoal)
    agent = Agent(ctx.get("sessions").create("goal-controls"), ctx=ctx)
    ctx.get("agents").register(agent)
    return ctx, agent, controls, command


async def invoke(ctx, agent, name, args, initiated=True):
    run = ToolRunContext(ToolExecutionInput("call-1", name, args, agent=agent, signal=None))
    tool = ctx.get("tools").get(name)
    if initiated:
        value = await ctx.get("agents").with_initiator_async(agent, tool.execute(args, run))
    else:
        value = await tool.execute(args, run)
    return value, run


@pytest.mark.asyncio
async def test_tools_require_live_open_driver_and_admitted_human_authority():
    ctx, agent, controls, _ = await setup()
    try:
        agent.set_status("running")
        agent.session.append("turn/start", {"turn": 1})
        agent.session.append_user_message("not a human", source={"kind": "plugin", "plugin": "test"})
        with pytest.raises(GoalError) as failure:
            await invoke(ctx, agent, "create_goal", {"objective": "work"})
        assert failure.value.code == "GOAL_TOOL_AUTHORITY_REQUIRED"
        agent.session.append_user_message("please finish this")
        with pytest.raises(GoalError) as failure:
            await invoke(ctx, agent, "create_goal", {"objective": "work"}, initiated=False)
        assert failure.value.code == "GOAL_TOOL_DRIVER_REQUIRED"
        value, _ = await invoke(ctx, agent, "create_goal", {"objective": "work"})
        assert value["goal"]["roundsStarted"] == 0 and value["activation"] == "armed"
        args = dict(goal_id=value["goal"]["id"], revision=1, action="pause", objective="", max_goal_rounds=0, blocked_reason="")
        value, _ = await invoke(ctx, agent, "update_goal", args)
        assert value["goal"]["phase"] == "paused"
        await controls.dispose()
        assert ctx.get("tools").get("create_goal") is None
    finally:
        agent.set_status("idle")
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_exact_goal_round_threshold_and_terminal_wrapup_context():
    ctx, agent, _, _ = await setup()
    goals = ctx.get("goals")
    try:
        goal = goals.create(agent, {"objective": 'finish "quoted" work'})
        agent.set_status("running")
        agent.session.append("turn/start", {"turn": 1})
        agent.session.append_user_message("continue", source={"kind": "goal", "goalId": goal["id"], "revision": 1, "round": 1})
        args = {"goal_id": goal["id"], "revision": 1, "action": "blocked", "blocked_reason": "requires account"}
        with pytest.raises(GoalError) as failure:
            await invoke(ctx, agent, "update_goal", args)
        assert failure.value.code == "GOAL_TOOL_BLOCK_THRESHOLD"
        args = dict(args, action="complete", blocked_reason="")
        result, run = await invoke(ctx, agent, "update_goal", args)
        assert result["goal"]["phase"] == "complete" and len(run._additional_contexts) == 1
        notice = run._additional_contexts[0]
        assert notice["source"]["form"] == "notice" and '\\"quoted\\"' in notice["content"][0]["text"]
        assert not run._concludes_turn
    finally:
        agent.set_status("idle")
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_human_commands_share_domain_and_preserve_objective_attachments():
    ctx, agent, _, command = await setup()
    commands, goals = ctx.get("commands"), ctx.get("goals")
    try:
        assert "No goal" in (await commands.execute(agent, "/goal")).result["text"]
        created = await commands.execute(agent, "/goal finish the migration")
        assert created.result["kind"] == "success"
        assert (await commands.execute(agent, "/goal pause")).result["kind"] == "success"
        assert goals.get(agent)["phase"] == "paused"
        assert (await commands.execute(agent, "/goal resume")).result["kind"] == "success"
        definition = commands.find(agent, "goal")
        image = {"type": "image", "mimeType": "image/png", "data": "already-admitted"}
        response = definition.handler(CommandInvocation("attachments", agent, "edit match this", [image], None))
        assert response["kind"] == "success"
        assert agent.inbox.next_turn[0]["content"][0] == image
        assert agent.inbox.next_turn[0]["source"] == {"kind": "user"}
        response = definition.handler(CommandInvocation("rejected", agent, "clear", [image], None))
        assert response["kind"] == "error" and goals.get(agent) is not None
        assert (await commands.execute(agent, "/goal clear")).result["text"] == "Goal cleared."
        await command.dispose()
        assert commands.find(agent, "goal") is None
    finally:
        agent.set_status("idle")
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_goal_change_observer_failure_does_not_fail_committed_tool_or_starve_peer():
    ctx, agent, _, _ = await setup()
    seen = []
    def broken(payload):
        raise RuntimeError("observer failure")
    ctx.on("goal/changed", broken)
    ctx.on("goal/changed", lambda payload: seen.append(payload["change"]["operation"]))
    try:
        agent.set_status("running")
        agent.session.append("turn/start", {"turn": 1})
        agent.session.append_user_message("finish this")
        value, _ = await invoke(ctx, agent, "create_goal", {"objective": "finish"})
        assert value["goal"]["revision"] == 1 and seen == ["create"]
    finally:
        agent.set_status("idle")
        await ctx.fiber.dispose()
