import pytest
from dsh.shell.terminal import quote_for_pwsh, quote_for_bash, PersistentTerminal
from dsh.shell.tool_pwsh import clamp_timeout, tail_bytes, stream_text, render_pwsh_result, build_shell_env


def test_quote_for_pwsh():
    raw = 'echo "Hello $world" `test\nnewline'
    quoted = quote_for_pwsh(raw)
    assert '`"' in quoted
    assert '`$' in quoted
    assert '``' in quoted
    assert '`n' in quoted


def test_quote_for_bash():
    raw = "echo 'Hello' \\ test\nnewline"
    quoted = quote_for_bash(raw)
    assert quoted.startswith("$'")
    assert "\\'" in quoted
    assert "\\n" in quoted


def test_clamp_timeout():
    assert clamp_timeout(None, 1000, 5000) == 1000
    assert clamp_timeout(3000, 1000, 5000) == 3000
    assert clamp_timeout(8000, 1000, 5000) == 5000


def test_tail_bytes():
    data = b"hello world from deepseek"
    text, trunc = tail_bytes(data, 10)
    assert trunc is True
    assert text == "m deepseek"

    text2, trunc2 = tail_bytes(data, 100)
    assert trunc2 is False
    assert text2 == "hello world from deepseek"


def test_stream_text():
    assert stream_text("output", False, None) == "output"
    assert "[output truncated; full output: /path/to/spill]" in stream_text("partial", True, "/path/to/spill")
    assert "[output truncated; full output: (unavailable)]" in stream_text("partial", True, None)


def test_render_pwsh_result():
    res1 = render_pwsh_result(
        stdout_text="line 1\nline 2",
        stdout_truncated=False,
        stderr_text="",
        stderr_truncated=False,
        exit_code=0,
        timed_out=False,
        timeout_ms=10000,
    )
    assert res1 == "line 1\nline 2"

    res2 = render_pwsh_result(
        stdout_text="line 1",
        stdout_truncated=False,
        stderr_text="warning 1",
        stderr_truncated=False,
        exit_code=1,
        timed_out=False,
        timeout_ms=10000,
    )
    assert "[stderr]\nwarning 1" in res2
    assert "[exit code: 1]" in res2

    res3 = render_pwsh_result(
        stdout_text="",
        stdout_truncated=False,
        stderr_text="",
        stderr_truncated=False,
        exit_code=0,
        timed_out=True,
        timeout_ms=5000,
    )
    assert "[timed out after 5000ms]" in res3