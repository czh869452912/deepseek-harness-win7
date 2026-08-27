import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture
async def plan_ctx():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    session = sessions.create("test-plan-session")

    # Cordis plugins are asynchronous fibers.  Mount plan mode below the
    # ask-user fiber so its caller-bound tool catalog inherits ask_user_question.
    ask_fiber = await ctx.registry.plugin(ToolAskUserPlugin, parent_ctx=ctx)
    plan_fiber = await ctx.registry.plugin(PlanModePlugin, parent_ctx=ask_fiber.ctx)
    try:
        yield plan_fiber.ctx
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_fold_plan_mode(plan_ctx):
    session = plan_ctx.get("sessions").get("test-plan-session")
    assert fold_plan_mode(session.events) is False

    session.append("plan/mode", {"active": True})
    assert fold_plan_mode(session.events) is True

    session.append("plan/mode", {"active": False})
    assert fold_plan_mode(session.events) is False


@pytest.mark.asyncio
async def test_plan_mode_prompt_assembly(plan_ctx):
    controller: PlanModeController = plan_ctx.get("plan_mode")
    base_prompt = "You are an assistant."

    # Inactive: prompt is unchanged
    assert controller.on_prompt_assemble(base_prompt) == base_prompt

    # Active: guidance is injected
    controller.set_active(True)
    assembled = controller.on_prompt_assemble(base_prompt)
    assert "[Plan Mode Active]" in assembled
    assert "You are in plan mode" in assembled

    controller.set_active(False)
    assert controller.on_prompt_assemble(base_prompt) == base_prompt


@pytest.mark.asyncio
async def test_exit_plan_mode_validation(plan_ctx):
    tools = plan_ctx.get("tools")
    exit_tool = tools.get_tool("exit_plan_mode", plan_ctx)
    assert exit_tool is not None

    controller: PlanModeController = plan_ctx.get("plan_mode")

    # 1. Calling exit_plan_mode while not active should fail
    res1 = await exit_tool.handler(plan="# Test Plan\nDetails...", ctx=plan_ctx)
    assert "only available when plan mode is active" in res1

    # 2. Activate plan mode
    controller.set_active(True)

    # 3. Invalid plan format (no # heading) should fail
    res2 = await exit_tool.handler(plan="This is not a markdown heading plan", ctx=plan_ctx)
    assert "requires a non-empty markdown plan starting with a # heading" in res2

    # 4. Valid plan format should succeed
    res3 = await exit_tool.handler(plan="# Architecture Refactor Plan\n1. Inspect modules\n2. Refactor", ctx=plan_ctx)
    assert "approved" in res3.lower()
    assert controller.is_active() is False


@pytest.mark.asyncio
async def test_plan_slash_command_hook(plan_ctx):
    plugin = plan_ctx.get("plugin:plan-mode")
    controller: PlanModeController = plan_ctx.get("plan_mode")

    # Hook /plan
    payload = {
        "messages": [{"role": "user", "content": "/plan"}]
    }
    await plan_ctx.waterfall("agent/pre-step", payload, lambda value: value)
    assert controller.is_active() is True

    # Hook /plan off
    payload_off = {
        "messages": [{"role": "user", "content": "/plan off"}]
    }
    await plan_ctx.waterfall("agent/pre-step", payload_off, lambda value: value)
    assert controller.is_active() is False
