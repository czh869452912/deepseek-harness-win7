import asyncio
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.jobs.jobs_service import JobsService


class ToolJobsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-jobs`: Model-facing background job controls (job_output, job_list, job_kill).
    """

    id = "tool-jobs"
    name = "@deepseek-ai/dsh-tool-jobs"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        if not ctx.has("jobs"):
            ctx.set_service("jobs", JobsService(ctx))

        jobs_svc: JobsService = ctx.get("jobs")

        async def exec_job_list() -> str:
            all_jobs = jobs_svc.list_jobs()
            if not all_jobs:
                return "No background jobs registered."
            lines = ["Background jobs:"]
            for j in all_jobs:
                lines.append(f"- ID: {j.id} [{j.status.upper()}] {j.label} (started at {j.started_at})")
            return "\n".join(lines)

        async def exec_job_output(id: str, wait: bool = False, timeout_ms: int = 30000) -> str:
            job = jobs_svc.get_job(id)
            if not job:
                return f"Error: No job found with ID '{id}'"

            if wait and job.status == "running":
                timeout_sec = min(600, max(1, timeout_ms / 1000.0))
                try:
                    await asyncio.wait_for(job._completion_event.wait(), timeout=timeout_sec)
                except asyncio.TimeoutError:
                    pass

            output_text = "".join(job.output_buffer)
            return (
                f"Job {job.id} status: {job.status}\n"
                f"Output:\n{output_text if output_text else '(No output)'}"
            )

        async def exec_job_kill(id: str) -> str:
            success = jobs_svc.kill_job(id)
            if success:
                return f"Successfully killed job '{id}'."
            return f"Error: Job '{id}' could not be killed (may not exist or already finished)."

        disposer1 = tools.register_tool({
            "name": "job_list",
            "description": "List background jobs owned by the current session with their status.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
            "execute": exec_job_list,
        })

        disposer2 = tools.register_tool({
            "name": "job_output",
            "description": "Retrieve the output of a background job, optionally waiting for its completion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The job ID to inspect"},
                    "wait": {"type": "boolean", "description": "Whether to wait for job completion"},
                    "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds when wait is true"},
                },
                "required": ["id"],
            },
            "execute": exec_job_output,
        })

        disposer3 = tools.register_tool({
            "name": "job_kill",
            "description": "Kill/terminate a running background job by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The job ID to kill"},
                },
                "required": ["id"],
            },
            "execute": exec_job_kill,
        })

        def cleanup():
            disposer1()
            disposer2()
            disposer3()

        ctx.effect(cleanup)
