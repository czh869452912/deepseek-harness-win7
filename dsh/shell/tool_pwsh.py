import asyncio
import os
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.jobs.jobs_service import JobsService

# UTF-8 output pinning prepended to every command (TS: pwsh-local ENCODING_PREAMBLE).
ENCODING_PREAMBLE = (
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
)

# Model-friendly environment overrides (TS: pwsh-local ENV_OVERRIDES).
ENV_OVERRIDES = {
    "NO_COLOR": "1",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
}

# Executor defaults (TS: pwsh-local Config defaults).
DEFAULT_TIMEOUT_MS = 120000
MAX_TIMEOUT_MS = 600000
MAX_OUTPUT_BYTES = 64000


def resolve_dsh_home() -> str:
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


def build_shell_env() -> Dict[str, str]:
    """Trusted per-execution DSH_* built-ins (TS: shell-env collect built-ins)."""
    env = dict(ENV_OVERRIDES)
    env["DSH_HOME"] = resolve_dsh_home()
    env["DSH_SHELL"] = "1"
    return env


def clamp_timeout(request_ms: Optional[int], default_ms: int, max_ms: int) -> int:
    if request_ms is None:
        return default_ms
    return min(request_ms, max_ms)


def tail_bytes(data: bytes, max_bytes: int) -> Any:
    """Keep the last max_bytes of a stream; returns (text, truncated)."""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace"), False
    return data[-max_bytes:].decode("utf-8", errors="replace"), True


def stream_text(text: str, truncated: bool, spill_path: Optional[str]) -> str:
    """TS render.streamText: append the truncation notice with the spill path."""
    if not truncated:
        return text
    return f"{text}\n[output truncated; full output: {spill_path if spill_path else '(unavailable)'}]"


def render_pwsh_result(
    stdout_text: str,
    stdout_truncated: bool,
    stderr_text: str,
    stderr_truncated: bool,
    exit_code: Optional[int],
    timed_out: bool,
    timeout_ms: int,
    stdout_spill: Optional[str] = None,
    stderr_spill: Optional[str] = None,
) -> str:
    """TS renderPwshResult: stdout, a marked stderr section, then exit-status markers."""
    out = stream_text(stdout_text, stdout_truncated, stdout_spill)
    err = stream_text(stderr_text, stderr_truncated, stderr_spill)

    body = out
    if len(err) > 0:
        if len(body) > 0 and not body.endswith("\n"):
            body += "\n"
        body += f"[stderr]\n{err}"
    if len(body) == 0:
        body = "(no output)"

    markers: List[str] = []
    if timed_out:
        markers.append(f"[timed out after {timeout_ms}ms]")
    elif exit_code is not None and exit_code != 0:
        markers.append(f"[exit code: {exit_code}]")
    if not markers:
        return body
    if not body.endswith("\n"):
        body += "\n"
    return body + "\n".join(markers)


def pwsh_description(background_enabled: bool) -> str:
    """TS pwshDescription without the sandbox-escalation suffix (no confining executor)."""
    background = (
        "Set `run_in_background: true` for long-running commands: the call returns a job id immediately; "
        "read its output with `job_output` and stop it with `job_kill`."
        if background_enabled
        else "Background execution is not available; long-running commands must finish within the timeout."
    )
    return (
        "Execute a PowerShell command (`pwsh -Command`) and return its stdout/stderr. "
        "Each call runs in a fresh pwsh process: no state (cwd, variables, functions) persists between calls — "
        "pass `workdir` instead of using `cd`. Paths use native Windows form (`C:\\...`); read environment "
        "variables with `$env:NAME`. Non-zero exits are reported as `[exit code: N]`. "
        "Current harness environment facts are exposed through managed `$env:DSH_*` variables; inspect them when needed. "
        "Commands may run under a file sandbox; a blocked file operation is reported as `[sandbox: file access denied under <mode> mode]` — a policy denial, not a bug in the command; do not retry another way. "
        "Long output is truncated to its tail; the full output is saved to a file whose path is reported when available. "
        "On Windows a force-killed command settles as `[exit code: 1]` without a signal marker — treat it as an interruption, not a command failure. "
        + background
    )


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
        self.default_timeout_ms = int(cfg.get("timeoutMs", DEFAULT_TIMEOUT_MS))
        self.max_timeout_ms = int(cfg.get("maxTimeoutMs", MAX_TIMEOUT_MS))
        self.max_output_bytes = int(cfg.get("maxOutputBytes", MAX_OUTPUT_BYTES))

    def _spawn_argv(self, command: str) -> List[str]:
        return [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            ENCODING_PREAMBLE + command,
        ]

    def _spawn_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env.update(build_shell_env())
        return env

    def _spill(self, ctx: Any, data: bytes) -> Optional[str]:
        spill_store = ctx.get("spillStore") if ctx and hasattr(ctx, "get") else None
        if not spill_store:
            return None
        try:
            return spill_store.write_spill(data.decode("utf-8", errors="replace"))
        except Exception:
            return None

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
            timeoutMs: Optional[int] = None,
            workdir: Optional[str] = None,
            run_in_background: bool = False,
        ) -> str:
            # TS validatePwshArgs
            if not command or not command.strip():
                return "Error: invalid command: expected a non-empty string"
            if description is not None and len(description.strip()) == 0:
                return "Error: invalid description: expected a non-empty string"
            if timeoutMs is not None and (not isinstance(timeoutMs, (int, float)) or timeoutMs <= 0):
                return f"Error: invalid timeoutMs: expected a positive number, got {timeoutMs}"

            eff_timeout_ms = clamp_timeout(timeoutMs, self.default_timeout_ms, self.max_timeout_ms)

            # TS resolveWorkdir: explicit workdir first; a relative one is session-workspace-relative.
            base_cwd = ctx.get("fs").cwd if ctx.has("fs") and hasattr(ctx.get("fs"), "cwd") else os.getcwd()
            if workdir is None:
                cwd = base_cwd
            elif not os.path.isabs(workdir):
                cwd = os.path.normpath(os.path.join(base_cwd, workdir))
            else:
                cwd = workdir

            if run_in_background:
                if not self.enable_run_in_background:
                    return "Error: run_in_background is disabled for this deployment (enableRunInBackground: false)"
                jobs: Optional[JobsService] = ctx.get("jobs")
                if not jobs:
                    return "Error: background jobs unavailable: load @deepseek-ai/dsh-jobs and @deepseek-ai/dsh-tool-jobs"

                async def bg_runner() -> str:
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            *self._spawn_argv(command),
                            cwd=cwd,
                            env=self._spawn_env(),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_bytes, stderr_bytes = await proc.communicate()
                        out_text, out_trunc = tail_bytes(stdout_bytes, self.max_output_bytes)
                        err_text, err_trunc = tail_bytes(stderr_bytes, self.max_output_bytes)
                        return render_pwsh_result(
                            out_text,
                            out_trunc,
                            err_text,
                            err_trunc,
                            proc.returncode,
                            False,
                            eff_timeout_ms,
                            self._spill(ctx, stdout_bytes) if out_trunc else None,
                            self._spill(ctx, stderr_bytes) if err_trunc else None,
                        )
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
                    *self._spawn_argv(command),
                    cwd=cwd,
                    env=self._spawn_env(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                timed_out = False
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=eff_timeout_ms / 1000.0,
                    )
                except asyncio.TimeoutError:
                    timed_out = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    # Collect whatever partial output the process produced.
                    stdout_bytes, stderr_bytes = await proc.communicate()

                out_text, out_trunc = tail_bytes(stdout_bytes, self.max_output_bytes)
                err_text, err_trunc = tail_bytes(stderr_bytes, self.max_output_bytes)

                return render_pwsh_result(
                    out_text,
                    out_trunc,
                    err_text,
                    err_trunc,
                    proc.returncode,
                    timed_out,
                    eff_timeout_ms,
                    self._spill(ctx, stdout_bytes) if out_trunc else None,
                    self._spill(ctx, stderr_bytes) if err_trunc else None,
                )

            except Exception as ex:
                return f"Error executing PowerShell command: {ex}"

        properties: Dict[str, Any] = {
            "command": {
                "type": "string",
                "description": "The PowerShell command to execute.",
            },
            "description": {
                "type": "string",
                "description": "Clear, concise description of what this command does in active voice, "
                "5-10 words (shown in the UI). Examples: \"ls\" → \"List files in current directory\"; "
                "\"git status\" → \"Show working tree status\"; \"Get-Process\" → \"List running processes\".",
            },
            "timeoutMs": {
                "type": "number",
                "description": "Timeout in milliseconds. The executor applies its configured default and cap, and kills the command on expiry.",
            },
            "workdir": {
                "type": "string",
                "description": "Working directory for this command. Defaults to the session workspace; a relative path is resolved against it.",
            },
        }
        if self.enable_run_in_background:
            properties["run_in_background"] = {
                "type": "boolean",
                "description": "Run in the background and return a job id immediately (collect with job_output, stop with job_kill). No timeout applies.",
            }

        d = tools.register_tool({
            "name": "pwsh",
            "description": pwsh_description(self.enable_run_in_background),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": ["command", "description"],
            },
            "execute": execute_pwsh,
        })

        ctx.effect(d)
