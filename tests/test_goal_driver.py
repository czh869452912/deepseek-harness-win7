from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.tools import ToolsPlugin
from dsh.goal.service import GoalService
from dsh.goal.driver import GoalRoundDriver
from dsh.goal.fold import goal_ref


class Model:
    provider, model = "mock", "mock"

    def __init__(self):
        self.requests = []
        self.entered = asyncio.Event()
        self.release = None

    async def chat_completion_stream(self, messages, tools=None, **kwargs):
        self.requests.append(messages)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        yield {"choices": [{"delta": {"content": "done", "role": "assistant"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


async def setup():
    ctx, model = Context(), Model()
    ctx.set_service("llm", model)
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(AgentLoopPlugin)
    await ctx.plugin(GoalService)
    driver = await ctx.plugin(GoalRoundDriver)
    handle = await ctx.get("agent_loop").create("goal-driver-test")
    return ctx, model, handle, driver


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 3)


@pytest.mark.asyncio
async def test_real_driver_admits_exact_rounds_and_blocks_at_durable_limit():
    ctx, model, handle, driver = await setup()
    agent, goals = handle.agent, ctx.get("goals")
    try:
        goals.create(agent, {"objective": "finish", "maxGoalRounds": 2})
        await until(lambda: goals.get(agent)["phase"] == "blocked")
        await agent.when_idle()
        goal = goals.get(agent)
        assert goal["roundsStarted"] == 2 and goal["blockedReason"]["code"] == "round-limit"
        assert len(model.requests) == 2
        sources = [event["data"]["source"] for event in agent.session.events if event["type"] == "user/message"]
        assert [source["round"] for source in sources if source["kind"] == "goal"] == [1, 2]
    finally:
        await driver.dispose()
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_edit_while_checkpoint_pending_never_admits_old_objective(monkeypatch):
    ctx, model, handle, driver = await setup()
    agent, goals = handle.agent, ctx.get("goals")
    entered, release = asyncio.Event(), asyncio.Event()
    sessions = ctx.get("sessions")
    original = sessions.flush
    async def flush(session):
        entered.set()
        await release.wait()
        return await original(session)
    monkeypatch.setattr(sessions, "flush", flush)
    try:
        first = goals.create(agent, {"objective": "old objective", "maxGoalRounds": 1})
        await entered.wait()
        goals.edit(agent, goal_ref(first), {"objective": "new objective"})
        release.set()
        await until(lambda: goals.get(agent)["phase"] == "blocked")
        messages = [event["data"] for event in agent.session.events if event["type"] == "user/message"]
        assert len(messages) == 1 and "new objective" in messages[0]["content"][0]["text"]
        assert messages[0]["source"]["revision"] == 2
    finally:
        release.set()
        await driver.dispose()
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_checkpoint_failure_disarms_and_downstream_rejection_blocks(monkeypatch):
    ctx, model, handle, driver = await setup()
    agent, goals = handle.agent, ctx.get("goals")
    sessions = ctx.get("sessions")
    original = sessions.flush
    async def broken(session):
        raise OSError("disk full")
    monkeypatch.setattr(sessions, "flush", broken)
    try:
        goals.create(agent, {"objective": "finish"})
        await until(lambda: goals.get(agent)["activation"] == "disarmed")
        assert not model.requests
        monkeypatch.setattr(sessions, "flush", original)
        ctx.on("agent/pre-step", lambda payload, next_fn: {"kind": "reject"})
        goals.resume(agent, goal_ref(goals.get(agent)))
        await until(lambda: goals.get(agent)["phase"] == "blocked")
        assert goals.get(agent)["blockedReason"]["code"] == "prompt-rejected"
        assert goals.get(agent)["roundsStarted"] == 0
    finally:
        await driver.dispose()
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_driver_disposal_cancels_inflight_round_and_drains_model():
    ctx, model, handle, driver = await setup()
    agent, goals = handle.agent, ctx.get("goals")
    model.release = asyncio.Event()
    try:
        goals.create(agent, {"objective": "finish"})
        await asyncio.wait_for(model.entered.wait(), 3)
        closing = asyncio.ensure_future(driver.dispose())
        await asyncio.sleep(0)
        model.release.set()
        await asyncio.wait_for(closing, 3)
        assert agent.status == "idle" and goals.get(agent)["activation"] == "disarmed"
        assert len(model.requests) == 1
    finally:
        model.release.set()
        await driver.dispose()
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_revision_change_during_pre_step_rejects_reserved_round():
    ctx, model, handle, driver = await setup()
    agent, goals = handle.agent, ctx.get("goals")
    entered, release = asyncio.Event(), asyncio.Event()
    first = True
    async def delayed(payload, next_fn):
        nonlocal first
        if first:
            first = False
            entered.set()
            await release.wait()
        return await next_fn()
    ctx.on("agent/pre-step", delayed)
    try:
        initial = goals.create(agent, {"objective": "obsolete", "maxGoalRounds": 1})
        await entered.wait()
        goals.edit(agent, goal_ref(initial), {"objective": "replacement"})
        release.set()
        await until(lambda: goals.get(agent)["phase"] == "blocked")
        assert len(model.requests) == 1
        messages = [event["data"] for event in agent.session.events if event["type"] == "user/message"]
        assert len(messages) == 1 and messages[0]["source"]["revision"] == 2
    finally:
        release.set()
        await driver.dispose()
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_user_cancel_pauses_goal_without_another_automatic_round():
    ctx, model, handle, driver = await setup()
    agent, goals = handle.agent, ctx.get("goals")
    model.release = asyncio.Event()
    try:
        goals.create(agent, {"objective": "finish"})
        await asyncio.wait_for(model.entered.wait(), 3)
        agent.cancel({"kind": "user"})
        model.release.set()
        await until(lambda: goals.get(agent)["phase"] == "paused")
        assert goals.get(agent)["activation"] == "disarmed" and len(model.requests) == 1
    finally:
        model.release.set()
        await driver.dispose()
        await handle.dispose()
        await ctx.fiber.dispose()
