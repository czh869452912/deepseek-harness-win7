import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.core.tools import ToolsPlugin
from dsh.goal.tool_goal import ToolGoalPlugin, GoalService, fold_goal_state, guidance


def fake_agent(ctx, name="agent-1"):
    sess_store = ctx.get("sessions")
    session = sess_store.create(name)
    agent = Agent(agent_id=name, session=session, ctx=ctx)
    ctx.get("agents").enter(agent)
    return agent


@pytest.fixture
def goal_ctx():
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    sess_plugin = SessionPlugin()
    sess_plugin.apply(ctx)
    agent_plugin = AgentPlugin()
    agent_plugin.apply(ctx)
    goal_plugin = ToolGoalPlugin({"blockedAfterConsecutiveRounds": 3})
    goal_plugin.apply(ctx)
    return ctx


def test_guidance_text():
    text = guidance(3)
    assert "for at least 3 consecutive goal rounds" in text
    assert "create_goal" in text
    assert "update_goal" in text


def test_fold_goal_state():
    events = []
    assert fold_goal_state(events) is None

    events.append({
        "type": "goal/change",
        "data": {
            "operation": "create",
            "goal": {
                "id": "goal-123",
                "revision": 1,
                "objective": "Build parser",
                "phase": "active",
                "roundsStarted": 1,
            },
        },
    })
    g = fold_goal_state(events)
    assert g is not None
    assert g.id == "goal-123"
    assert g.revision == 1
    assert g.objective == "Build parser"
    assert g.phase == "active"

    events.append({
        "type": "goal/change",
        "data": {
            "operation": "pause",
            "goal": {
                "id": "goal-123",
                "revision": 2,
                "objective": "Build parser",
                "phase": "paused",
            },
        },
    })
    g2 = fold_goal_state(events)
    assert g2.phase == "paused"
    assert g2.revision == 2


def test_create_and_update_goal_service(goal_ctx):
    ctx = goal_ctx
    agent = fake_agent(ctx, "agent-g1")
    goal_svc: GoalService = ctx.get("goals")

    g = goal_svc.create_goal(objective="Refactor codebase", max_goal_rounds=10, agent=agent)
    assert g.objective == "Refactor codebase"
    assert g.revision == 1
    assert g.phase == "active"

    # CAS Revision mismatch should raise error
    with pytest.raises(ValueError, match="Revision mismatch"):
        goal_svc.update_goal(g.id, revision=99, action="pause", agent=agent)

    # Pause goal
    g_paused = goal_svc.update_goal(g.id, revision=1, action="pause", agent=agent)
    assert g_paused.phase == "paused"
    assert g_paused.revision == 2

    # Resume goal
    g_resumed = goal_svc.update_goal(g.id, revision=2, action="resume", agent=agent)
    assert g_resumed.phase == "active"
    assert g_resumed.revision == 3

    # Edit goal objective
    g_edited = goal_svc.update_goal(g.id, revision=3, action="edit", objective="Refactor codebase v2", agent=agent)
    assert g_edited.objective == "Refactor codebase v2"
    assert g_edited.revision == 4

    # Complete goal
    g_done = goal_svc.update_goal(g.id, revision=4, action="complete", agent=agent)
    assert g_done.phase == "complete"
    assert g_done.revision == 5