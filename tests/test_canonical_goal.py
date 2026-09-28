import copy

import pytest

from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import SessionPlugin
from dsh.goal.service import GoalService, GoalError
from dsh.goal.fold import fold_goal, goal_ref, apply_goal_projection


async def setup():
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(AgentPlugin)
    fiber = await ctx.plugin(GoalService)
    agent = Agent(ctx.get("sessions").create("goal-test"), ctx=ctx)
    ctx.get("agents").register(agent)
    return ctx, agent, ctx.get("goals"), fiber


@pytest.mark.asyncio
async def test_cas_mutations_tombstone_and_restart_disarm():
    ctx, agent, goals, fiber = await setup()
    try:
        view = goals.create(agent, {"objective": "  finish the migration  ", "maxGoalRounds": 2})
        assert view["roundsStarted"] == 0 and view["activation"] == "armed"
        assert view["objective"] == "finish the migration"
        saved = goal_ref(view)
        view["objective"] = "mutated by caller"
        assert goals.get(agent)["objective"] == "finish the migration"
        paused = goals.pause(agent, saved)
        with pytest.raises(GoalError) as stale:
            goals.edit(agent, saved, {"objective": "wrong"})
        assert stale.value.code == "GOAL_STALE_REVISION"
        resumed = goals.resume(agent, goal_ref(paused))
        await fiber.dispose()
        await ctx.plugin(GoalService)
        goals = ctx.get("goals")
        recovered = goals.get(agent)
        assert recovered["activation"] == "disarmed" and recovered["revision"] == resumed["revision"]
        resumed = goals.resume(agent, goal_ref(recovered))
        tombstone = goals.clear(agent, goal_ref(resumed))
        assert goals.get(agent) is None
        assert fold_goal(agent.session.events)["lastRef"] == tombstone
        created = goals.create(agent, {"objective": "new"})
        assert created["id"] != saved["id"]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_round_admission_replay_budget_and_exact_live_identity():
    ctx, agent, goals, _ = await setup()
    try:
        view = goals.create(agent, {"objective": "work", "maxGoalRounds": 1})
        agent.session.append_user_message("continue", message_id="goal-round",
            source={"kind": "goal", "goalId": view["id"], "revision": view["revision"], "round": 1})
        assert goals.get(agent)["roundsStarted"] == 1
        blocked = goals.block(agent, goal_ref(view), {"code": "round-limit", "message": "  exhausted  "})
        assert blocked["blockedReason"]["message"] == "exhausted"
        with pytest.raises(GoalError) as error:
            goals.resume(agent, goal_ref(blocked))
        assert error.value.code == "GOAL_INVALID_TRANSITION"
        edited = goals.edit(agent, goal_ref(blocked), {"maxGoalRounds": 2})
        assert goals.resume(agent, goal_ref(edited))["activation"] == "armed"
        impostor = Agent(agent.session, ctx=ctx)
        with pytest.raises(GoalError) as error:
            goals.get(impostor)
        assert error.value.code == "GOAL_AGENT_NOT_LIVE"
        events = copy.deepcopy(agent.session.events)
        round_event = next(event for event in events if event["type"] == "user/message")
        round_event["data"]["source"]["round"] = 2
        with pytest.raises(ValueError, match="next admitted"):
            fold_goal(events)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_projection_ignores_corruption_but_domain_replay_rejects_it():
    ctx, agent, goals, _ = await setup()
    try:
        goals.create(agent, {"objective": "work"})
        event = copy.deepcopy(agent.session.events[-1])
        projection = apply_goal_projection(None, event)
        assert projection["roundsStarted"] == 0
        event["data"]["goal"]["extra"] = True
        assert apply_goal_projection(projection, event) is projection
        with pytest.raises(ValueError, match="exactly"):
            fold_goal([event])
        for value in (True, 0, -1, 1.5, 9007199254740992):
            with pytest.raises(GoalError):
                goals.edit(agent, goal_ref(goals.get(agent)), {"maxGoalRounds": value})
    finally:
        await ctx.fiber.dispose()
