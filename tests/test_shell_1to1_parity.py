import os
import sys
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.jobs.jobs_service import JobsService
from dsh.shell.render import parse_exit_status
from dsh.shell.terminal import (
    SHELL_RESET_MESSAGE_BASH,
    SHELL_RESET_MESSAGE_PWSH,
    PersistentTerminal,
    TerminalService,
    quote_for_bash,
    quote_for_pwsh,
)
from dsh.shell.tool_pwsh import ToolPwshPlugin, clamp_timeout, render_pwsh_result
from dsh.shell.tool_pwsh_persistent import ToolPwshPersistentPlugin, maybe_truncate


def test_parse_exit_status_clean():
    res = parse_exit_status("Hello World\nLine 2")
    assert res["body"] == "Hello World\nLine 2"
    assert res["exit_code"] == 0
    assert "signal" not in res


def test_parse_exit_status_code_marker():
    res = parse_exit_status("Process failed\n[exit code: 127]")
    assert res["body"] == "Process failed"
    assert res["exit_code"] == 127


def test_parse_exit_status_signal_marker():
    res = parse_exit_status("Terminated output\n[killed by signal: SIGKILL]")
    assert res["body"] == "Terminated output"
    assert res["signal"] == "SIGKILL"


def test_quote_helpers():
    raw = 'echo "test $var" `cmd` \r\n \x1b[31m'
    pwsh_escaped = quote_for_pwsh(raw)
    assert '`"' in pwsh_escaped
    assert '`$' in pwsh_escaped
    assert '``' in pwsh_escaped
    assert '`n' in pwsh_escaped
    assert '`e' in pwsh_escaped

    bash_escaped = quote_for_bash("echo 'hello \\ world'")
    assert bash_escaped.startswith("$'")
    assert "\\'" in bash_escaped
    assert "\\\\" in bash_escaped


def test_persistent_terminal_bash_subshell_persistence(tmp_path):
    # Test bash persistence without subshell state loss
    if sys.platform == "win32":
        # Check if bash is installed on windows (e.g. Git Bash or WSL bash)
        import shutil
        if not shutil.which("bash"):
            pytest.skip("bash not available on Windows host")

    term = PersistentTerminal(shell_type="bash", cwd=str(tmp_path))
    code1, out1, reset1 = term.execute("export DSH_TEST_VAR=harness_1234")
    assert code1 == 0
    assert not reset1

    code2, out2, reset2 = term.execute('echo "VAR_VALUE=$DSH_TEST_VAR"')
    assert code2 == 0
    assert not reset2
    assert "VAR_VALUE=harness_1234" in out2
    term.reset()


def test_tool_pwsh_persistent_validation():
    with pytest.raises(ValueError, match="backendType must be non-empty"):
        ToolPwshPersistentPlugin({"backendType": "  "})

    with pytest.raises(ValueError, match="timeoutMs must be a positive safe integer"):
        ToolPwshPersistentPlugin({"timeoutMs": 0})

    with pytest.raises(ValueError, match="maxOutputChars must be a positive safe integer"):
        ToolPwshPersistentPlugin({"maxOutputChars": -5})

    with pytest.raises(ValueError, match="description must be non-empty"):
        ToolPwshPersistentPlugin({"description": "   "})


def test_render_pwsh_result_formatting():
    res = render_pwsh_result(
        stdout_text="output line 1\noutput line 2",
        stdout_truncated=False,
        stderr_text="error warning",
        stderr_truncated=False,
        exit_code=1,
        timed_out=False,
        timeout_ms=120000,
    )
    assert "output line 1" in res
    assert "[stderr]\nerror warning" in res
    assert "[exit code: 1]" in res


def test_clamp_timeout():
    assert clamp_timeout(None, 120000, 600000) == 120000
    assert clamp_timeout(50000, 120000, 600000) == 50000
    assert clamp_timeout(900000, 120000, 600000) == 600000
