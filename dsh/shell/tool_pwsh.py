import asyncio
import os
import sys
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.jobs.jobs_service import JobsService


class ToolPwshPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-pwsh`: Exposes one-shot PowerShell execution tool `pwsh`.
    Supports foreground execution with timeout, CWD override, and `run_in_background: true`
    which offloads long-running commands to the JobsService.
    """

    id = "tool-pwsh"
    name = "@deepseek-ai/dsh-tool-pwsh"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.enable_run_in_background = bool(cfg.get("enableRunInBackground", True))
        self.default_timeout_ms = int(cfg.get("timeoutMs", 60000))

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        if ctx.has("system_prompt"):
            sp = ctx.get("system_prompt")
            if hasattr(sp, "section"):
                sp.section(
                    "tool:pwsh",
                    "Non-zero exits are reported as `[exit code: N]` markers; investigate failures before moving on. "
                    "On Windows a killed process settles as `[exit code: 1]` without a signal marker; treat a bare exit 1 after an interruption as a termination, not a command failure.",
                    order=105,
                )

        async def execute_pwsh(
            command: str,
            description: Optional[str] = None,
            timeout_ms: Optional[int] = None,
            timeoutMs: Optional[int] = None,
            workdir: Optional[str] = None,
            run_in_background: bool = False,
        ) -> str:
            if not command or not command.strip():
                return "Error: command must be a non-empty string."

            eff_timeout_ms = timeout_ms or timeoutMs or self.default_timeout_ms
            cwd = workdir or (ctx.get("fs").cwd if ctx.has("fs") and hasattr(ctx.get("fs"), "cwd") else os.getcwd())

            if run_in_background:
                if not self.enable_run_in_background:
                    return "Error: run_in_background is disabled in this configuration."
                jobs: Optional[JobsService] = ctx.get("jobs")
                if not jobs:
                    return "Error: background jobs service unavailable."

                async def bg_runner() -> str:
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "powershell.exe",
                            "-NoProfile",
                            "-NonInteractive",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-Command",
                            command,
                            cwd=cwd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_bytes, stderr_bytes = await proc.communicate()
                        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
                        stderr_str = stderr_bytes.decode("utf-8", errors="replace")
                        exit_code = proc.returncode
                        res_lines = []
                        if stdout_str:
                            res_lines.append(stdout_str)
                        if stderr_str:
                            res_lines.append(stderr_str)
                        if exit_code != 0:
                            res_lines.append(f"\n[exit code: {exit_code}]")
                        return "\n".join(res_lines)
                    except Exception as e:
                        return f"Error executing background command: {e}"

                job = jobs.submit_job(
                    name=description or command[:40],
                    task_coro=bg_runner(),
                    metadata={"command": command, "workdir": cwd},
                )
                return f"Started background job {job.id} (collect with job_output, stop with job_kill)"

            # Foreground execution with timeout
            try:
                proc = await asyncio.create_subprocess_exec(
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=eff_timeout_ms / 1000.0,
                    )
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return f"[Error: command timed out after {eff_timeout_ms}ms]"

                stdout_str = stdout_bytes.decode("utf-8", errors="replace")
                stderr_str = stderr_bytes.decode("utf-8", errors="replace")
                exit_code = proc.returncode

                output_parts = []
                if stdout_str:
                    output_parts.append(stdout_str)
                if stderr_str:
                    output_parts.append(stderr_str)
                if exit_code != 0:
                    output_parts.append(f"\n[exit code: {exit_code}]")

                return "\n".join(output_parts) if output_parts else "[Command finished with no output]"

            except Exception as ex:
                return f"Error executing PowerShell command: {ex}"

        d = tools.register_tool({
            "name": "pwsh",
            "description": (
                "Execute a PowerShell command (`pwsh -Command`) and return its stdout/stderr. "
                "Each call runs in a fresh pwsh process. Paths use native Windows form (`C:\\...`); "
                "read environment variables with `$env:NAME`. "
                "Set `run_in_background: true` for long-running commands."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The PowerShell command to execute.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Clear, concise description of what this command does in active voice.",
                    },
                    "timeoutMs": {
                        "type": "number",
                        "description": "Timeout in milliseconds.",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory for this command.",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "Run in the background and return a job id immediately.",
                    },
                },
                "required": ["command"],
            },
            "execute": execute_pwsh,
        })

        ctx.effect(d)
