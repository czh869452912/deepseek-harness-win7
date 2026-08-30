import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionStore
from dsh.core.tools import ToolsService
from dsh.interaction.tool_ask_user import ToolAskUserPlugin
from dsh.plan.plan_mode import (
    PlanModePlugin,
    PlanModeController,
    fold_plan_mode,
    DEFAULT_PLAN_GUIDANCE,
)


from dsh.core.agent import Agent, AgentPlugin


@pytest.fixture
def plan_ctx():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    session = sessions.create("test-plan-session")
    AgentPlugin().apply(ctx)
    agent = Agent(session=session, ctx=ctx, agent_id="test-plan-session")
    ctx.get("agents").enter(agent)

    ctx.plugin(ToolAskUserPlugin)
    ctx.plugin(PlanModePlugin, config={"section": DEFAULT_PLAN_GUIDANCE})
    return ctx


def test_fold_plan_mode(plan_ctx):
    session = plan_ctx.get("sessions").get("test-plan-session")
    assert fold_plan_mode(session.events) is False

    session.append("plan/mode", {"active": True})
    assert fold_plan_mode(session.events) is True

    session.append("plan/mode", {"active": False})
    assert fold_plan_mode(session.events) is False


def test_plan_mode_prompt_assembly(plan_ctx):
    controller: PlanModeController = plan_ctx.get("planMode")
    agent = plan_ctx.get("agents").get("test-plan-session")
    base_prompt = "You are an assistant."

    # Inactive: prompt is unchanged
    assert controller.on_prompt_assemble(base_prompt) == base_prompt

    # Active: guidance is injected
    controller.set(agent, True)
    assert controller.is_active(agent) is True
    assembled = controller.on_prompt_assemble(base_prompt)
    assert "[Plan Mode Active]" in assembled
    assert "You are in plan mode" in assembled

    controller.set(agent, False)
    assert controller.on_prompt_assemble(base_prompt) == base_prompt


@pytest.mark.asyncio
async def test_exit_plan_mode_validation(plan_ctx):
    tools = plan_ctx.get("tools")
    controller: PlanModeController = plan_ctx.get("planMode")
    agent = plan_ctx.get("agents").get("test-plan-session")

    # 1. Calling exit_plan_mode while not active should fail
    res1 = await tools.execute({
        "name": "exit_plan_mode",
        "arguments": {"plan": "# Test Plan\nDetails..."},
        "agent": agent,
    })
    assert res1.is_error is True
    assert "only available in plan mode" in res1.content[0]["text"]

    # 2. Activate plan mode
    controller.set(agent, True)

    # 3. Invalid plan format (no # heading) should fail
    res2 = await tools.execute({
        "name": "exit_plan_mode",
        "arguments": {"plan": "This is not a markdown heading plan"},
        "agent": agent,
    })
    assert res2.is_error is True
    assert "requires a non-empty markdown plan starting with a # heading" in res2.content[0]["text"]

    # 4. Valid plan format should succeed
    res3 = await tools.execute({
        "name": "exit_plan_mode",
        "arguments": {"plan": "# Architecture Refactor Plan\n1. Inspect modules\n2. Refactor"},
        "agent": agent,
    })
    assert res3.is_error is False
    assert "approved" in res3.content[0]["text"].lower()
    assert controller.is_active(agent) is False
