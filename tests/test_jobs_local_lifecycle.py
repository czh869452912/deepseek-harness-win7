import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.scope import create_scope, ScopeKey
from dsh.jobs.local import LocalJobRegistry


async def mounted():
    ctx = Context()
    fiber = await ctx.plugin(LocalJobRegistry, config={"maxConcurrentJobsPerOwner": 1})
    return ctx, fiber, ctx.get("jobs")


def producer():
    done = asyncio.get_running_loop().create_future()
    reasons = []
    def cancel(reason):
        reasons.append(reason)
        if not done.done():
            done.set_result({"status": "killed"})
    return dict(done=done, cancel=cancel), reasons


@pytest.mark.asyncio
async def test_admission_precedes_start_and_stopping_counts_toward_limit():
    ctx, _, jobs = await mounted()
    calls = []
    hooks, _ = producer()
    spec = dict(kind="shell", label="command", run=lambda: (calls.append(True) or hooks))
    try:
        with pytest.raises(ValueError, match="controller"):
            jobs.start(spec)
        assert calls == []
        jobs.attach_controller("tests")
        first = jobs.start(spec)
        assert first == "shell-1"
        with pytest.raises(ValueError, match="limit"):
            jobs.start(spec)
        assert calls == [True]
        assert jobs.kill(first) == "requested"
        with pytest.raises(ValueError, match="limit"):
            jobs.start(spec)
        assert (await jobs.wait(first, 1000))["status"] == "killed"
        snap = jobs.get(first)
        snap["label"] = "mutated"
        assert jobs.get(first)["label"] == "command"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_owner_isolation_and_scoped_controller_visibility():
    ctx, _, jobs = await mounted()
    from dsh.core.agent import Agent, AgentRegistry
    from dsh.core.session import Session
    registry = AgentRegistry(ctx)
    ctx.set_service("agents", registry)
    a_ctx = create_scope(ctx, ScopeKey("a")).ctx
    b_ctx = create_scope(ctx, ScopeKey("b")).ctx
    a, b = Agent(Session("a"), ctx=a_ctx), Agent(Session("b"), ctx=b_ctx)
    registry.register(a)
    registry.register(b)
    a_ctx.get("jobs").attach_controller("a-only")
    hooks, _ = producer()
    try:
        with pytest.raises(ValueError, match="controller"):
            jobs.start(dict(kind="shell", label="private", owner=b, run=lambda: hooks))
        job_id = jobs.start(dict(kind="shell", label="private", owner=a, run=lambda: hooks))
        assert jobs.list(b) == jobs.list() == []
        with pytest.raises(ValueError, match="another session"):
            jobs.read(job_id, b)
        hooks["done"].set_result({"status": "completed", "output": "result"})
        await jobs.wait(job_id, 1000, a)
        assert jobs.read(job_id, a)["text"] == "result"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_wait_timeout_does_not_cancel_and_settlement_notifies_after_committing():
    ctx, _, jobs = await mounted()
    jobs.attach_controller("test")
    seen = []
    jobs.on_jobs_changed(lambda _: seen.append(("change", jobs.list())))
    jobs.on_job_done(lambda snap, _: seen.append(("done", jobs.get(snap["id"]))))
    hooks, reasons = producer()
    job_id = jobs.start(dict(kind="task", label="test", run=lambda: hooks))
    try:
        assert (await jobs.wait(job_id, 1))["status"] == "running"
        assert reasons == []
        waiting = asyncio.create_task(jobs.wait(job_id, 1000))
        await asyncio.sleep(0)
        hooks["done"].set_result({"status": "completed", "output": "done"})
        assert (await waiting)["reported"]
        assert seen[-2][0] == "change" and seen[-1][0] == "done"
        assert seen[-1][1]["reported"]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_teardown_throwing_cancel_force_fails_record_without_hanging(caplog):
    ctx, fiber, jobs = await mounted()
    jobs.attach_controller("test")
    done = asyncio.get_running_loop().create_future()
    def fail(_):
        raise RuntimeError("broken producer")
    jobs.start(dict(kind="task", label="test", run=lambda: dict(done=done, cancel=fail)))
    await asyncio.wait_for(fiber.dispose(), 1)
    assert "may be orphaned" in caplog.text
    done.set_result({"status": "completed"})
    await asyncio.sleep(0)
    assert jobs.list() == []
    await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("abort_first", [False, True])
async def test_wait_settlement_and_abort_order_preserves_completion_notice(abort_first):
    from dsh.core.abort import AbortController
    ctx, _, jobs = await mounted()
    jobs.attach_controller("test")
    hooks, _ = producer()
    controller = AbortController()
    seen = []
    def on_done(snapshot, owner):
        seen.append(snapshot)
        controller.abort()
    jobs.on_job_done(on_done)
    job_id = jobs.start(dict(kind="task", label="race", run=lambda: hooks))
    try:
        pending = asyncio.create_task(jobs.wait(job_id, 1000, signal=controller.signal))
        await asyncio.sleep(0)
        if abort_first:
            controller.abort()
        hooks["done"].set_result({"status": "completed"})
        if abort_first:
            with pytest.raises(RuntimeError, match="wait aborted"):
                await pending
        else:
            assert (await pending)["reported"]
        await asyncio.sleep(0)
        assert seen[0]["reported"] is (not abort_first)
        assert not controller.signal._listeners
    finally:
        await ctx.fiber.dispose()
