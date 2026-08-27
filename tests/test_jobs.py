import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.jobs.jobs_service import JobsService
from dsh.jobs.tool_jobs import ToolJobsPlugin


@pytest.mark.asyncio
async def test_jobs_service_and_tools():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    # Reactive plugin activation is asynchronous; wait for the Fiber before
    # reading injected services, matching the upstream lifecycle contract.
    fiber = await ctx.registry.plugin(ToolJobsPlugin, parent_ctx=ctx)

    jobs_svc: JobsService = ctx.get("jobs")
    assert jobs_svc is not None

    # Create a job
    job = jobs_svc.create_job(kind="build", label="Build frontend", owner_session_id="session-1")
    job.append_output("Compiling TypeScript...\n")
    job.append_output("Build finished successfully.\n")
    job.mark_finished(status="completed")

    # Plugin-owned tool registrations live in its scoped Context.
    tools = fiber.ctx.get("tools")

    # List jobs
    list_res = await tools.execute_tool("job_list", {})
    assert "Build frontend" in list_res
    assert job.id in list_res

    # Output job
    out_res = await tools.execute_tool("job_output", {"job_id": job.id, "wait": False})
    assert "Compiling TypeScript" in out_res
    assert "completed" in out_res

    # Kill job test
    job2 = jobs_svc.create_job(kind="daemon", label="Server watcher", owner_session_id="session-1")
    kill_res = await tools.execute_tool("job_kill", {"job_id": job2.id})
    assert "Successfully killed" in kill_res
    assert job2.status == "killed"
