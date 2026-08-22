import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

SHELL_RESET_MESSAGE = (
    "The persistent pwsh shell was reset; the next pwsh call starts from the workspace "
    "with a fresh current directory and environment."
)


def quote_for_pwsh(value: str) -> str:
    """
    Escape a command body for embedding in the PowerShell wrapper's double-quoted string.
    Backticks escape: ` -> ``, " -> `", $ -> `$, \r -> '', \n -> `n, \x1b -> `e.
    """
    return (
        value.replace("`", "``")
        .replace('"', '`"')
        .replace("$", "`$")
        .replace("\r", "")
        .replace("\n", "`n")
        .replace("\x1b", "`e")
    )


class PersistentTerminal:
    """
    True persistent Shell execution engine for Windows 7 (PowerShell) and POSIX (Bash).
    Maintains variables, working directory, and environment across command calls.
    """

    def __init__(self, shell_type: str = "auto", cwd: Optional[str] = None):
        self.cwd = cwd or os.getcwd()
        self.shell_type = shell_type
        if self.shell_type == "auto":
            self.shell_type = "powershell" if sys.platform == "win32" else "bash"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._start_process()

    def _start_process(self) -> None:
        if self.shell_type == "powershell":
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-NoLogo",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "-",
            ]
        elif self.shell_type == "cmd":
            cmd = ["cmd.exe", "/k", "prompt $P$G"]
        else:
            cmd = ["bash", "--login", "-i"]

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if self.shell_type == "powershell":
                preamble = (
                    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false);\n"
                )
                self._proc.stdin.write(preamble)
                self._proc.stdin.flush()
        except Exception as e:
            print(f"[PersistentTerminal Error] Failed to start shell process: {e}")
            self._proc = None

    def reset(self) -> None:
        """Terminate and restart the persistent shell process."""
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None
            self._start_process()

    def execute(self, command: str, timeout_seconds: int = 300) -> Tuple[int, str, bool]:
        """
        Execute command in the persistent shell session and wait for completion marker.
        Returns (exit_code, output_text, was_reset).
        """
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._start_process()
                if self._proc is None:
                    return -1, "Error: Shell process could not be started.", True

            nonce = uuid.uuid4().hex
            start_marker = f"__DSH_PERSISTENT_PWSH_START_{nonce}__"
            end_marker = f"__DSH_PERSISTENT_PWSH_END_{nonce}:"

            if self.shell_type == "powershell":
                body = quote_for_pwsh(command)
                wrapper = (
                    f"Write-Output '{start_marker}'; $LASTEXITCODE = $null; $__s = 1; "
                    f'try {{ Invoke-Expression "{body}"; $__ok = $? }} catch {{ $__ok = $false }}; '
                    f"if ($null -ne $LASTEXITCODE) {{ $__s = [int]$LASTEXITCODE }} else {{ $__s = if ($__ok) {{ 0 }} else {{ 1 }} }}; "
                    f"Write-Output ('{end_marker}' + $__s)\n"
                )
            else:
                # POSIX Bash wrapper
                escaped = command.replace("'", "'\\''")
                wrapper = (
                    f"echo '{start_marker}'; (eval '{escaped}'); __s=$?; "
                    f"echo '{end_marker}'$__s\n"
                )

            try:
                self._proc.stdin.write(wrapper)
                self._proc.stdin.flush()
            except Exception as e:
                self.reset()
                return -1, f"Failed writing to shell stdin: {e}", True

            # Read output with timeout
            output_lines: List[str] = []
            started = False
            exit_code = 0
            completed = False

            q: queue.Queue = queue.Queue()

            import re

            def reader_thread():
                while True:
                    line = self._proc.stdout.readline()
                    if not line:
                        q.put(None)
                        break
                    q.put(line)
                    if re.search(re.escape(end_marker) + r"\d+", line):
                        break

            t = threading.Thread(target=reader_thread, daemon=True)
            t.start()

            deadline = time.time() + timeout_seconds

            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                try:
                    line = q.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue

                if line is None:
                    # Process died unexpectedly
                    self.reset()
                    return -1, "\n".join(output_lines) + "\n(Shell process exited unexpectedly)", True

                line_clean = line.rstrip("\r\n")

                if start_marker in line_clean and not started:
                    started = True
                    continue

                match = re.search(re.escape(end_marker) + r"(\d+)", line_clean)
                if match:
                    exit_code = int(match.group(1))
                    completed = True
                    break

                if started:
                    output_lines.append(line_clean)

            if not completed:
                # Timed out
                self.reset()
                partial = "\n".join(output_lines)
                msg = (
                    f"Your command timed out after {timeout_seconds} seconds or experienced an OOM error. "
                    f"Below is partial output:\n{partial}\n{SHELL_RESET_MESSAGE}"
                )
                return -1, msg, True

            return exit_code, "\n".join(output_lines), False


class TerminalService:
    """
    Terminal service mounted at `ctx.terminal`.
    """

    def __init__(self, cwd: Optional[str] = None):
        self.terminal = PersistentTerminal(cwd=cwd)

    def run_command(self, command: str, timeout_seconds: int = 300) -> Dict[str, Any]:
        exit_code, output, was_reset = self.terminal.execute(command, timeout_seconds=timeout_seconds)
        return {
            "exit_code": exit_code,
            "output": output,
            "was_reset": was_reset,
        }

