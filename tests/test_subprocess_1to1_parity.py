"""
Unit tests for dsh.subprocess 1:1 parity with @deepseek-ai/dsh-subprocess.
"""

import asyncio
import os
import sys
import pytest

from dsh.cordis.context import Context
from dsh.subprocess import (
    child_env,
    CollectedOutput,
    DSH_ENV_PREFIX,
    LocalSubprocessRuntime,
    OutputCollector,
    SENSITIVE_ENV_PATTERN,
    scrubbed_parent_env,
    SubprocessCollect,
    SubprocessOutcome,
    SubprocessSpawnSpec,
    SubprocessStdio,
)


def test_scrubbed_parent_env():
    os.environ["TEST_SECRET_KEY"] = "supersecret"
    os.environ["DSH_AGENT_NAME"] = "deepseek"
    os.environ["SAFE_PATH_VAR"] = "/usr/bin"

    scrubbed = scrubbed_parent_env()
    assert "TEST_SECRET_KEY" not in scrubbed
    assert "DSH_AGENT_NAME" not in scrubbed
    assert "SAFE_PATH_VAR" in scrubbed

    os.environ.pop("TEST_SECRET_KEY", None)
    os.environ.pop("DSH_AGENT_NAME", None)
    os.environ.pop("SAFE_PATH_VAR", None)


def test_output_collector_tail_keep_and_spill(tmp_path):
    collector = OutputCollector(
        max_bytes=10,
        max_spill_bytes=50,
        label="test_out",
        spill_dir=str(tmp_path),
    )

    # 1. Push 5 bytes -> no spill, not truncated
    collector.push(b"hello")
    res1 = collector.read_from(0)
    assert res1.text == "hello"
    assert res1.lossy is False

    # 2. Push 10 bytes -> total 15 bytes -> exceeds max_bytes 10 -> triggers spill & tail truncation
    collector.push(b"world12345")
    final_out = collector.finalize()
    assert len(final_out.text) == 10
    assert final_out.truncated is True
    assert final_out.spillPath is not None
    assert os.path.exists(final_out.spillPath)


@pytest.mark.asyncio
async def test_subprocess_resolve_executable():
    ctx = Context()
    runtime = LocalSubprocessRuntime(ctx)

    # Relative path with slash must raise ValueError
    with pytest.raises(ValueError) as exc:
        await runtime.resolve_executable("./some/relative/cmd")
    assert "relative path" in str(exc.value)

    # Empty command must raise ValueError
    with pytest.raises(ValueError) as exc:
        await runtime.resolve_executable("")
    assert "executable must be non-empty" in str(exc.value)

    # Resolve python or cmd/bash executable
    py_exec = sys.executable
    resolved = await runtime.resolve_executable(py_exec)
    assert os.path.isabs(resolved)


@pytest.mark.asyncio
async def test_subprocess_spawn_and_collect():
    ctx = Context()
    runtime = LocalSubprocessRuntime(ctx)

    spec = SubprocessSpawnSpec(
        argv=[sys.executable, "-c", "import sys; sys.stdout.write('hello stdout'); sys.stderr.write('hello stderr')"],
        cwd=os.getcwd(),
        stdio=SubprocessStdio(
            stdin="ignore",
            stdout=SubprocessCollect(max_bytes=100),
            stderr=SubprocessCollect(max_bytes=100),
        ),
        grace_ms=1000,
    )

    handle = runtime.spawn(spec)
    assert handle.pid > 0

    outcome = await handle.done
    assert outcome.exitCode == 0

    out_read = handle.collected.stdout.read_from(0)
    err_read = handle.collected.stderr.read_from(0)

    assert out_read.text == "hello stdout"
    assert err_read.text == "hello stderr"


@pytest.mark.asyncio
async def test_subprocess_stdin_data_and_pipe():
    ctx = Context()
    runtime = LocalSubprocessRuntime(ctx)

    spec = SubprocessSpawnSpec(
        argv=[sys.executable, "-c", "import sys; data = sys.stdin.read(); print('ECHO:' + data)"],
        cwd=os.getcwd(),
        stdio=SubprocessStdio(
            stdin={"data": "input_payload"},
            stdout=SubprocessCollect(max_bytes=100),
            stderr="inherit",
        ),
        grace_ms=1000,
    )

    handle = runtime.spawn(spec)
    outcome = await handle.done
    assert outcome.exitCode == 0

    out_read = handle.collected.stdout.read_from(0)
    assert "ECHO:input_payload" in out_read.text
