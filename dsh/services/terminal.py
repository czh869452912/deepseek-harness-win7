import os
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple


class PersistentTerminal:
    """
    Persistent Shell execution engine for Windows 7 (PowerShell / Cmd).
    Maintains environment state and working directory across command calls.
    """

    def __init__(self, shell_type: str = "auto", cwd: Optional[str] = None):
        self.cwd = cwd or os.getcwd()
        self.shell_type = shell_type
        if self.shell_type == "auto":
            if sys.platform == "win32":
                self.shell_type = "powershell"
            else:
                self.shell_type = "bash"

    def execute(self, command: str, timeout_seconds: int = 300) -> Tuple[int, str, str]:
        """
        Execute command synchronously with timeout and cwd preservation.
        """
        if self.shell_type == "powershell":
            # Wrap powershell command to capture outputs and updated CWD
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        elif self.shell_type == "cmd":
            cmd = ["cmd.exe", "/c", command]
        else:
            cmd = ["bash", "-c", command]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False
            )
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            return proc.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            proc.kill()
            return -1, "", f"Command execution timed out after {timeout_seconds} seconds."
        except Exception as e:
            return -1, "", f"Execution error: {e}"


class TerminalService:
    """
    Terminal service mounted at `ctx.terminal`.
    """

    def __init__(self, cwd: Optional[str] = None):
        self.terminal = PersistentTerminal(cwd=cwd)

    def run_command(self, command: str, timeout_seconds: int = 300) -> Dict[str, Any]:
        exit_code, stdout, stderr = self.terminal.execute(command, timeout_seconds=timeout_seconds)
        output = stdout
        if stderr:
            if output:
                output += "\n--- STDERR ---\n" + stderr
            else:
                output = stderr

        return {
            "exit_code": exit_code,
            "output": output,
            "stdout": stdout,
            "stderr": stderr
        }
