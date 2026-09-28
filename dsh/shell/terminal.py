import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

SHELL_RESET_MESSAGE_PWSH = (
    "The persistent pwsh shell was reset; the next pwsh call starts from the workspace "
    "with a fresh current directory and environment."
)
SHELL_RESET_MESSAGE_BASH = (
    "The persistent bash shell was reset; the next bash call starts from the workspace "
    "with a fresh current directory and environment."
)
SHELL_RESET_MESSAGE = SHELL_RESET_MESSAGE_PWSH


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


def quote_for_bash(value: str) -> str:
    """
    Escape a command body for embedding in bash eval string using $'...' format.
    Backslash escapes: \\ -> \\\\, ' -> \\', \\r -> \\r, \\n -> \\n.
    """
    return "$'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\r", "\\r").replace("\n", "\\n") + "'"


class PersistentTerminal:
    """
    True persistent Shell execution engine for Windows 7 (PowerShell) and POSIX (Bash).
    Maintains variables, working directory, and environment across command calls.
    """

    def __init__(self, shell_type: str = "auto", cwd: Optional[str] = None):
        self.cwd = cwd or os.getcwd()
        self.shell_type = "powershell" if shell_type == "pwsh" else shell_type
        if self.shell_type == "auto":
            self.shell_type = "powershell" if sys.platform == "win32" else "bash"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._closed = False

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
            executable = shutil.which("bash") or "bash"
            if sys.platform == "win32":
                # The system32 WSL launcher is not a native persistent shell.
                for base in (os.environ.get("ProgramFiles", "C:/Program Files"),
                             os.environ.get("LOCALAPPDATA", "")):
                    candidate = os.path.join(base, "Git", "bin", "bash.exe")
                    if os.path.isfile(candidate):
                        executable = candidate
                        break
            cmd = [executable, "--noprofile", "--norc"]

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
                start_new_session=sys.platform != "win32",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if self.shell_type == "powershell":
                preamble = (
                    "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
                    "$OutputEncoding = [Console]::OutputEncoding;\n"
                )
                self._proc.stdin.write(preamble)
                self._proc.stdin.flush()
        except Exception as e:
            if "logger" in sys.modules:
                pass
            sys.stderr.write(f"[PersistentTerminal Error] Failed to start shell process: {e}\n")
            self._proc = None

    def _stop_locked(self) -> None:
        process, self._proc = self._proc, None
        if process is None:
            return
        try:
            if sys.platform == "win32" and process.poll() is None:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            elif sys.platform != "win32":
                os.killpg(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

    def reset(self) -> None:
        """Retire the current process; the next command starts a fresh shell."""
        with self._lock:
            self._stop_locked()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_locked()

    def execute(self, command: str, timeout_seconds: int = 300, cancelled=None) -> Tuple[int, str, bool]:
        """
        Execute command in the persistent shell session and wait for completion marker.
        Returns (exit_code, output_text, was_reset).
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("persistent terminal is closed")
            if self._proc is None or self._proc.poll() is not None:
                self._start_process()
                if self._proc is None:
                    return -1, "Error: Shell process could not be started.", True

            nonce = uuid.uuid4().hex
            prefix = "PWSH" if self.shell_type == "powershell" else "BASH"
            start_marker = f"__DSH_PERSISTENT_{prefix}_START_{nonce}__"
            end_marker = f"__DSH_PERSISTENT_{prefix}_END_{nonce}:"

            if self.shell_type == "powershell":
                body = quote_for_pwsh(command)
                wrapper = (
                    f"Write-Output '{start_marker}'; $LASTEXITCODE = $null; $__s = 1; "
                    f'try {{ Invoke-Expression "{body}"; $__ok = $? }} catch {{ $__ok = $false }}; '
                    f"if ($null -ne $LASTEXITCODE) {{ $__s = [int]$LASTEXITCODE }} else {{ $__s = if ($__ok) {{ 0 }} else {{ 1 }} }}; "
                    f"Write-Output ('{end_marker}' + $__s)\n"
                )
            else:
                # POSIX Bash wrapper without subshell parentheses so cd & export persist
                body = quote_for_bash(command)
                wrapper = (
                    f"printf '%s\\n' '{start_marker}'; eval -- {body}; __s=$?; "
                    f"printf '%s%s\\n' '{end_marker}' \"$__s\"\n"
                )

            try:
                self._proc.stdin.write(wrapper)
                self._proc.stdin.flush()
            except Exception as e:
                self._stop_locked()
                return -1, f"Failed writing to shell stdin: {e}", True

            # Read output with timeout
            output_lines: List[str] = []
            started = False
            exit_code = 0
            completed = False

            q: queue.Queue = queue.Queue()

            process = self._proc

            def reader_thread():
                while True:
                    try:
                        line = process.stdout.readline()
                    except (OSError, ValueError):
                        q.put(None)
                        break
                    if not line:
                        q.put(None)
                        break
                    q.put(line)
                    if re.search(re.escape(end_marker) + r"-?\d+", line):
                        break

            t = threading.Thread(target=reader_thread, daemon=True)
            t.start()

            deadline = time.monotonic() + timeout_seconds

            while time.monotonic() < deadline:
                if cancelled is not None and cancelled.is_set():
                    self._stop_locked()
                    return -1, "Command cancelled; persistent shell reset.", True
                remaining = max(0.1, deadline - time.monotonic())
                try:
                    line = q.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue

                if line is None:
                    # Process died unexpectedly
                    self._stop_locked()
                    return -1, "\n".join(output_lines) + "\n(Shell process exited unexpectedly)", True

                line_clean = line.rstrip("\r\n")

                if start_marker in line_clean and not started:
                    started = True
                    continue

                match = re.search(re.escape(end_marker) + r"(-?\d+)", line_clean)
                if match:
                    exit_code = int(match.group(1))
                    completed = True
                    break

                if started:
                    output_lines.append(line_clean)

            if not completed:
                # Timed out
                self._stop_locked()
                partial = "\n".join(output_lines)
                reset_msg = (
                    SHELL_RESET_MESSAGE_BASH
                    if self.shell_type == "bash"
                    else SHELL_RESET_MESSAGE_PWSH
                )
                msg = (
                    f"Your command timed out after {timeout_seconds} seconds or experienced an OOM error. "
                    f"Below is partial output:\n{partial}\n{reset_msg}"
                )
                return -1, msg, True

            return exit_code, "\n".join(output_lines), False


class TerminalService:
    """
    Terminal service mounted at `ctx.terminal` or `ctx.terminals`.
    """

    def __init__(self, cwd: Optional[str] = None, shell_type: str = "auto"):
        self.terminal = PersistentTerminal(shell_type=shell_type, cwd=cwd)

    def run_command(self, command: str, timeout_seconds: int = 300, cancelled=None) -> Dict[str, Any]:
        exit_code, output, was_reset = self.terminal.execute(command, timeout_seconds=timeout_seconds, cancelled=cancelled)
        return {
            "exit_code": exit_code,
            "output": output,
            "was_reset": was_reset,
            "completed": not was_reset,
        }

    def reset(self) -> None:
        self.terminal.reset()

    def close(self) -> None:
        self.terminal.close()
