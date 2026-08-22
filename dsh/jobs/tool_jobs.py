import asyncio
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.jobs.jobs_service import JobsService


SYSTEM_PROMPT_JOBS_TEXT = (
    "Track every background job id you start. You are notified in-session when a job finishes — "
    "do not busy-poll or sleep on one; keep working on independent steps and do not duplicate a running job's work. "
    "Before giving a final answer, collect every still-relevant job with job_output "
    "(set wait: true only when you are genuinely blocked on it), and job_kill jobs that stopped mattering."
)


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

        if ctx.has("system_prompt"):
            sp = ctx.get("system_prompt")
            if hasattr(sp, "section"):
                sp.section("tool:jobs", SYSTEM_PROMPT_JOBS_TEXT, order=106)

        async def exec_job_list() -> str:
            all_jobs = jobs_svc.list_jobs()
            if not all_jobs:
                return "No background jobs registered."
            lines = ["Background jobs:"]
            for j in all_jobs:
                lines.append(f"- ID: {j.id} [{j.status.upper()}] {j.label} (started at {j.started_at})")
            return "\n".join(lines)

        async def exec_job_output(
            job_id: Optional[str] = None,
            id: Optional[str] = None,
            wait: bool = False,
            timeout_ms: int = 30000,
        ) -> str:
            target_id = job_id or id
            if not target_id:
                return "Error: job_id parameter is required"

            job = jobs_svc.get_job(target_id)
            if not job:
                return f"Error: No job found with ID '{target_id}'"

            if wait and job.status == "running":
                timeout_sec = min(600, max(1, timeout_ms / 1000.0))
                try:
                    await asyncio.wait_for(job._completion_event.wait(), timeout=timeout_sec)
                except asyncio.TimeoutError:
                    pass

            output_text = "".join(job.output_buffer)
            return (
                f"Job {job.id} status: {job.status}\n"
                f"Output:\n{output_text if output_text else '(No output)'}\n"
                f"[status: {job.status}]"
            )

        async def exec_job_kill(
            job_id: Optional[str] = None,
            id: Optional[str] = None,
            reason: Optional[str] = None,
        ) -> str:
            target_id = job_id or id
            if not target_id:
                return "Error: job_id parameter is required"

            success = jobs_svc.kill_job(target_id)
            if success:
                msg = f"Successfully killed job '{target_id}'."
                if reason:
                    msg += f" (reason: {reason})"
                return msg
            return f"Error: Job '{target_id}' could not be killed (may not exist or already finished)."

        disposer1 = tools.register_tool({
            "name": "job_list",
            "description": "List your background jobs (running and finished) with their ids, kinds, and statuses.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
            "execute": exec_job_list,
        })

        disposer2 = tools.register_tool({
            "name": "job_output",
            "description": "Read a background job output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id returned by the tool that started the background work."},
                    "id": {"type": "string", "description": "Legacy alias for job_id."},
                    "wait": {"type": "boolean", "description": "Whether to wait for job completion."},
                    "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds when wait is true."},
                },
                "required": ["job_id"],
            },
            "execute": exec_job_output,
        })

        disposer3 = tools.register_tool({
            "name": "job_kill",
            "description": "Request cancellation of a running background job by job id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id returned by the tool that started the background work."},
                    "id": {"type": "string", "description": "Legacy alias for job_id."},
                    "reason": {"type": "string", "description": "Optional short reason for cancellation."},
                },
                "required": ["job_id"],
            },
            "execute": exec_job_kill,
        })

        def cleanup():
            disposer1()
            disposer2()
            disposer3()

        ctx.effect(cleanup)

