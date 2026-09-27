import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionStore
from dsh.core.tools import ToolsService
from dsh.goal.tool_goal import GoalService, ToolGoalPlugin, fold_goal_state


@pytest.fixture
def goal_ctx():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    sessions.create("test-goal-session")

    ctx.plugin(ToolGoalPlugin)
    return ctx


def test_fold_goal_state(goal_ctx):
    session = goal_ctx.get("sessions").get("test-goal-session")
    assert fold_goal_state(session.events) is None

    session.append("goal/change", {
        "operation": "create",
        "goal": {
            "id": "goal-1",
            "revision": 1,
            "objective": "Build Win7 Harness",
            "phase": "active",
            "roundsStarted": 1,
            "maxGoalRounds": 10,
        }
    })
    goal = fold_goal_state(session.events)
    assert goal is not None
    assert goal.id == "goal-1"
    assert goal.objective == "Build Win7 Harness"
    assert goal.phase == "active"


def test_goal_service_crud(goal_ctx):
    goal_svc: GoalService = goal_ctx.get("goals")
    assert goal_svc is not None

    # 1. Create goal
    g1 = goal_svc.create_goal(objective="Ship standard mode", max_goal_rounds=15)
    assert g1.objective == "Ship standard mode"
    assert g1.revision == 1
    assert g1.phase == "active"

    # 2. Get goal
    g_curr = goal_svc.get_goal()
    assert g_curr is not None
    assert g_curr.id == g1.id

    # 3. Update goal (pause)
    g2 = goal_svc.update_goal(goal_id=g1.id, revision=1, action="pause")
    assert g2.phase == "paused"
    assert g2.revision == 2

    # 4. Update goal (resume)
    g3 = goal_svc.update_goal(goal_id=g1.id, revision=2, action="resume")
    assert g3.phase == "active"
    assert g3.revision == 3

    # 5. Update goal (complete)
    g4 = goal_svc.update_goal(goal_id=g1.id, revision=3, action="complete")
    assert g4.phase == "complete"
    assert g4.revision == 4


def test_goal_tool_handlers(goal_ctx):
    tools = goal_ctx.get("tools")
    create_tool = tools.get_tool("create_goal")
    get_tool = tools.get_tool("get_goal")
    update_tool = tools.get_tool("update_goal")

    assert create_tool is not None
    assert get_tool is not None
    assert update_tool is not None

    # Create via tool
    res_create = create_tool.handler(objective="Implement complete test suite", max_goal_rounds=5, ctx=goal_ctx)
    assert "goal" in res_create
    gid = res_create["goal"]["id"]

    # Get via tool
    res_get = get_tool.handler(ctx=goal_ctx)
    assert res_get["goal"]["id"] == gid

    # Update via tool (complete)
    res_update = update_tool.handler(goal_id=gid, revision=1, action="complete", ctx=goal_ctx)
    assert res_update["goal"]["phase"] == "complete"


@pytest.mark.asyncio
async def test_goal_slash_command(goal_ctx):
    goal_svc: GoalService = goal_ctx.get("goals")

    # Hook /goal <objective>
    payload = {
        "messages": [{"role": "user", "content": "/goal Refactor codebase"}]
    }
    await goal_ctx.waterfall("agent/pre-step", payload, lambda value: value)
    goal = goal_svc.get_goal()
    assert goal is not None
    assert goal.objective == "Refactor codebase"
    assert goal.phase == "active"

    # Hook /goal pause
    payload_pause = {
        "messages": [{"role": "user", "content": "/goal pause"}]
    }
    await goal_ctx.waterfall("agent/pre-step", payload_pause, lambda value: value)
    assert goal_svc.get_goal().phase == "paused"


def test_goal_blocked_threshold(goal_ctx):
    goal_svc: GoalService = goal_ctx.get("goals")
    g = goal_svc.create_goal(objective="Difficult task")
    assert g.activation == "armed"

    # Blocked without reason raises error
    with pytest.raises(ValueError, match="blocked_reason is required"):
        goal_svc.update_goal(goal_id=g.id, revision=1, action="blocked", blocked_reason="")

    # Blocked during goal round before 3 rounds raises threshold error
    with pytest.raises(ValueError, match="blocked requires at least 3 consecutive goal rounds"):
        goal_svc.update_goal(
            goal_id=g.id,
            revision=1,
            action="blocked",
            blocked_reason="Missing API key",
            is_goal_round=True,
        )

    # Blocked outside goal round succeeds
    g_blocked = goal_svc.update_goal(
        goal_id=g.id,
        revision=1,
        action="blocked",
        blocked_reason="Missing API key",
        is_goal_round=False,
    )
    assert g_blocked.phase == "blocked"
    assert g_blocked.activation == "disarmed"
    assert g_blocked.blocked_reason["message"] == "Missing API key"
