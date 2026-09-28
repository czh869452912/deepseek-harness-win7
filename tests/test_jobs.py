import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.core.system_prompt.service import SystemPrompt
from dsh.jobs.local import LocalJobRegistry
from dsh.jobs.tool_jobs import ToolJobsPlugin


@pytest.mark.asyncio
async def test_jobs_service_and_tools():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(LocalJobRegistry)
    fiber = await ctx.plugin(ToolJobsPlugin)
    jobs = ctx.get("jobs")
    done = asyncio.get_running_loop().create_future()
    try:
        job_id = jobs.start(dict(kind="build", label="Build frontend", run=lambda: dict(done=done, cancel=lambda _: None)))
        done.set_result({"status": "completed", "output": "Compiling TypeScript...\nBuild finished successfully."})
        await jobs.wait(job_id, 1000)
        tools = fiber.ctx.get("tools")
        list_res = await tools.execute_tool("job_list", {})
        assert "Build frontend" in list_res
        assert job_id in list_res
        out_res = await tools.execute_tool("job_output", {"job_id": job_id, "wait": False})
        assert "Compiling TypeScript" in out_res
        assert "[status: completed]" in out_res
        cancelled = asyncio.get_running_loop().create_future()
        second = jobs.start(dict(kind="daemon", label="Server watcher", run=lambda: dict(
            done=cancelled, cancel=lambda _: cancelled.set_result({"status": "killed"}))))
        kill_res = await tools.execute_tool("job_kill", {"job_id": second})
        assert "requested cancellation" in kill_res
        assert (await jobs.wait(second, 1000))["status"] == "killed"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_tools_hide_other_sessions_and_bound_output_and_completion_wakes():
    from dsh.core.agent import Agent, AgentRegistry
    from dsh.core.session import Session
    from dsh.core.tools import ToolExecutionInput
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    registry = AgentRegistry(ctx)
    ctx.set_service("agents", registry)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(LocalJobRegistry)
    fiber = await ctx.plugin(ToolJobsPlugin, config={"maxConsecutiveWakes": 1})
    a, b = Agent(Session("a"), ctx=ctx), Agent(Session("b"), ctx=ctx)
    registry.register(a)
    registry.register(b)
    jobs, tools = ctx.get("jobs"), fiber.ctx.get("tools")
    async def call(name, args, owner):
        return await tools.execute(ToolExecutionInput("call", name, args, agent=owner, signal=None))
    try:
        done = asyncio.get_running_loop().create_future()
        job_id = jobs.start(dict(kind="test", label="private", owner=a, outputLimitBytes=40,
                                run=lambda: dict(done=done, cancel=lambda _: None)))
        denied = await call("job_output", {"job_id": job_id}, b)
        assert denied.is_error and "another session" in denied.content[0]["text"]
        assert (await call("job_list", {}, b)).value == []
        done.set_result({"status": "completed", "output": "Long output " * 100})
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(a.inbox.next_turn) == 1
        assert b.inbox.is_empty()
        result = await call("job_output", {"job_id": job_id}, a)
        assert not result.is_error
        assert "ownerSession" not in result.value["job"]
        assert len(result.content[0]["text"].encode("utf-8")) <= 40
        assert result.content[0]["text"].endswith("[status: completed]")
        a.inbox.clear()
        a.set_phase("idle")
        next_done = asyncio.get_running_loop().create_future()
        jobs.start(dict(kind="test", label="next", owner=a,
                        run=lambda: dict(done=next_done, cancel=lambda _: None)))
        next_done.set_result({"status": "completed"})
        for _ in range(3):
            await asyncio.sleep(0)
        assert a.status == "idle" and not a.inbox.next_turn and len(a.inbox.next_step) == 1
        await fiber.dispose()
        assert not ctx.get("tools").has("job_output")
        with pytest.raises(ValueError, match="controller"):
            jobs.start(dict(kind="test", label="uncontrolled", run=lambda: None))
    finally:
        await ctx.fiber.dispose()
