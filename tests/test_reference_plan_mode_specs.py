import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.core.tools import ToolsPlugin
from dsh.interaction.user_questions import UserQuestionsPlugin
from dsh.plan.plan_mode import PlanModePlugin, resolve_config, fold_plan_mode, EXIT_PLAN_MODE


def fake_agent(ctx, name="agent-1", active=False):
    sess_store = ctx.get("sessions")
    session = sess_store.create(name)
    if active:
        session.append("plan/mode", {"active": True})
    agent = Agent(agent_id=name, session=session, ctx=ctx)
    ctx.get("agents").enter(agent)
    return agent


@pytest.fixture
def plan_ctx():
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    sess_plugin = SessionPlugin()
    sess_plugin.apply(ctx)
    agent_plugin = AgentPlugin()
    agent_plugin.apply(ctx)
    uq_plugin = UserQuestionsPlugin()
    uq_plugin.apply(ctx)
    plan_plugin = PlanModePlugin({"section": "Test plan guidance"})
    plan_plugin.apply(ctx)
    return ctx


def test_resolve_config():
    with pytest.raises(TypeError, match="needs a string `section`"):
        resolve_config({})

    with pytest.raises(TypeError, match="needs a string `section`"):
        resolve_config({"section": 123})

    with pytest.raises(ValueError, match="needs a non-empty `section`"):
        resolve_config({"section": "   "})

    with pytest.raises(ValueError, match="unknown key\\(s\\)"):
        resolve_config({"section": "abc", "extra": 1})

    res = resolve_config({"section": "Valid plan text"})
    assert res == {"section": "Valid plan text"}


def test_fold_plan_mode():
    events = []
    assert fold_plan_mode(events) is False
    events.append({"type": "plan/mode", "data": {"active": True}})
    events.append({"type": "plan/mode", "data": {"active": False}})
    events.append({"type": "plan/mode", "data": {"active": True}})
    assert fold_plan_mode(events) is True
    assert fold_plan_mode(events, end=2) is False
    assert fold_plan_mode(events, end=1) is True


def test_plan_mode_get_and_set(plan_ctx):
    ctx = plan_ctx
    agent = fake_agent(ctx, "agent-gs")
    plan_svc = ctx.get("planMode")

    assert plan_svc.get(agent) == {"active": False}
    res = plan_svc.set(agent, True)
    assert res == "committed"
    assert plan_svc.get(agent) == {"active": True}
    assert fold_plan_mode(agent.session.events) is True


@pytest.mark.asyncio
async def test_exit_plan_mode_requires_agent(plan_ctx):
    ctx = plan_ctx
    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": EXIT_PLAN_MODE,
        "arguments": {"plan": "# My Plan\nStep 1"},
    })
    assert res.is_error is True
    assert "requires a calling agent" in res.content[0]["text"]


@pytest.mark.asyncio
async def test_exit_plan_mode_rejects_outside_plan_mode(plan_ctx):
    ctx = plan_ctx
    agent = fake_agent(ctx, "agent-idle", active=False)
    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": EXIT_PLAN_MODE,
        "arguments": {"plan": "# My Plan\nStep 1"},
        "agent": agent,
    })
    assert res.is_error is True
    assert "only available in plan mode" in res.content[0]["text"]


@pytest.mark.asyncio
async def test_exit_plan_mode_rejects_invalid_markdown(plan_ctx):
    ctx = plan_ctx
    agent = fake_agent(ctx, "agent-active", active=True)
    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": EXIT_PLAN_MODE,
        "arguments": {"plan": "not a heading plan"},
        "agent": agent,
    })
    assert res.is_error is True
    assert "requires a non-empty markdown plan starting with a # heading" in res.content[0]["text"]


@pytest.mark.asyncio
async def test_exit_plan_mode_asks_user_and_exits_on_approval(plan_ctx):
    ctx = plan_ctx
    agent = fake_agent(ctx, "agent-active2", active=True)
    uq_svc = ctx.get("userQuestions")

    # Register provider that approves
    async def approve_provider(req):
        return {"answers": [{"id": "plan-review", "selected": ["Approve"]}]}

    uq_svc.register_provider(approve_provider)

    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": EXIT_PLAN_MODE,
        "arguments": {"plan": "# Architectural Migration\n1. Move files\n2. Add tests"},
        "agent": agent,
    })
    assert res.is_error is False
    assert "Plan approved — plan mode exited" in res.content[0]["text"]

    plan_svc = ctx.get("planMode")
    assert plan_svc.get(agent)["active"] is False