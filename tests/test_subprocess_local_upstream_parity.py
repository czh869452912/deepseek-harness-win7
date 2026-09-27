import asyncio
import os
import sys
import tempfile
import time

import pytest

from dsh.cordis.context import Context
from dsh.subprocess import (
    LocalSubprocessRuntime,
    SubprocessCollect,
    SubprocessSpawnSpec,
    SubprocessStdio,
)
from dsh.subprocess.collector import OutputCollector
from dsh.subprocess import local as subprocess_local


def _sleep_spec(signal=None, seconds=5, grace_ms=100):
    return SubprocessSpawnSpec(
        argv=[sys.executable, "-c", "import time; time.sleep(%s)" % seconds],
        cwd=os.getcwd(),
        stdio=SubprocessStdio(
            stdin="ignore",
            stdout=SubprocessCollect(1024),
            stderr=SubprocessCollect(1024),
        ),
        grace_ms=grace_ms,
        signal=signal,
    )


@pytest.mark.asyncio
async def test_preaborted_signal_rejects_before_spawn():
    runtime = LocalSubprocessRuntime(Context())
    signal = asyncio.Event()
    signal.set()

    with pytest.raises(Exception, match="aborted before spawn"):
        runtime.spawn(_sleep_spec(signal=signal))


@pytest.mark.asyncio
async def test_mid_run_signal_terminates_the_real_process_tree():
    runtime = LocalSubprocessRuntime(Context())
    signal = asyncio.Event()
    handle = runtime.spawn(_sleep_spec(signal=signal))
    signal.set()

    outcome = await asyncio.wait_for(handle.done, 2)
    assert outcome.exitCode is None or outcome.exitCode != 0
    if sys.platform != "win32":
        assert outcome.signal in ("SIGTERM", "SIGKILL")


@pytest.mark.asyncio
async def test_wait_for_exit_returns_false_when_its_bound_aborts():
    runtime = LocalSubprocessRuntime(Context())
    handle = runtime.spawn(_sleep_spec())
    bound = asyncio.Event()
    bound.set()

    try:
        assert await asyncio.wait_for(handle.wait_for_exit(bound), 0.5) is False
        assert handle.done.done() is False
    finally:
        handle.terminate()
        await asyncio.wait_for(handle.done, 2)


@pytest.mark.asyncio
async def test_context_dispose_terminates_and_joins_owned_processes():
    ctx = Context()
    runtime = LocalSubprocessRuntime(ctx)
    handle = runtime.spawn(_sleep_spec())

    await asyncio.wait_for(ctx.fiber.dispose(), 2)

    assert handle.done.done()
    assert runtime.live == set()


@pytest.mark.asyncio
async def test_terminal_allocation_honors_preaborted_signal():
    runtime = LocalSubprocessRuntime(Context())
    signal = asyncio.Event()
    signal.set()
    from dsh.subprocess import SubprocessTerminalSpawnSpec

    spec = SubprocessTerminalSpawnSpec(
        argv=[sys.executable, "-c", "pass"], cwd=os.getcwd(), rows=24,
        cols=80, grace_ms=100, signal=signal,
    )
    with pytest.raises(Exception, match="abort"):
        await runtime.spawn_terminal(spec)


@pytest.mark.asyncio
async def test_dispose_all_settles_and_clears_ownership_on_wait_failure():
    runtime = LocalSubprocessRuntime(Context())
    loop = asyncio.get_event_loop()

    class Handle:
        def __init__(self, fail=False):
            self.done = loop.create_future()
            self.done.set_result(None)
            self.fail = fail
            self.terminated = False
            self.force_terminated = False

        def terminate(self):
            self.terminated = True

        def terminate_for_host_exit(self):
            self.force_terminated = True

        async def wait_for_exit(self):
            if self.fail:
                raise RuntimeError("wait failed")
            return True

    failed = Handle(True)
    settled = Handle(False)
    runtime.live.update([failed, settled])

    with pytest.raises(RuntimeError, match="wait failed"):
        await runtime._dispose_managed_processes()

    assert failed.terminated and settled.terminated
    assert failed.force_terminated and settled.force_terminated
    assert runtime.live == set()


def test_default_spill_directory_is_process_private():
    collector = OutputCollector(1, 16, "stdout")

    assert os.path.dirname(collector.spill_dir) == tempfile.gettempdir()
    assert os.path.basename(collector.spill_dir).startswith("dsh-subprocess-")
    assert os.path.basename(collector.spill_dir) != "dsh-subprocess-spill"


def test_non_finite_grace_is_rejected_before_spawn():
    runtime = LocalSubprocessRuntime(Context())
    spec = _sleep_spec(seconds=0)
    spec.argv = ["definitely-not-a-real-executable"]
    spec.graceMs = float("nan")

    with pytest.raises(ValueError, match="positive finite"):
        runtime.spawn(spec)


@pytest.mark.asyncio
async def test_collected_pipe_drain_is_bounded_when_descendant_inherits_stdout():
    runtime = LocalSubprocessRuntime(Context())
    child = (
        "import subprocess,sys; "
        "sys.stdout.write('parent-output\\n'); sys.stdout.flush(); "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])"
    )
    spec = SubprocessSpawnSpec(
        argv=[sys.executable, "-c", child],
        cwd=os.getcwd(),
        stdio=SubprocessStdio(
            stdin="ignore",
            stdout=SubprocessCollect(1024),
            stderr=SubprocessCollect(1024),
        ),
        grace_ms=100,
    )

    started = time.monotonic()
    handle = runtime.spawn(spec)
    outcome = await asyncio.wait_for(asyncio.shield(handle.done), 0.8)
    elapsed = time.monotonic() - started

    assert outcome.exitCode == 0
    assert elapsed < 0.8
    read = handle.collected.stdout.read_from(0)
    assert read.text.replace("\r\n", "\n") == "parent-output\n"
    assert read.lossy is False and read.nextOffset == len(read.text.encode("utf-8"))
    deadline = asyncio.get_event_loop().time() + 0.3
    while (not handle._proc.stdout.closed or not handle._proc.stderr.closed):
        assert asyncio.get_event_loop().time() < deadline
        await asyncio.sleep(0.01)
    assert handle._pump_task.done()


def test_windows_executable_candidates_read_path_and_pathext_case_insensitively(
        monkeypatch, tmp_path):
    runtime = LocalSubprocessRuntime(Context())
    monkeypatch.setattr(subprocess_local.sys, "platform", "win32")

    candidates = runtime._executable_candidates(
        "custom", {"pAtH": str(tmp_path), "PathExt": ".FOO;.BAR"})

    assert candidates == [
        os.path.abspath(os.path.join(str(tmp_path), "custom.FOO")),
        os.path.abspath(os.path.join(str(tmp_path), "custom.BAR")),
    ]


def test_posix_group_signal_failure_falls_back_to_direct_child(monkeypatch):
    delivered = []
    monkeypatch.setattr(subprocess_local.sys, "platform", "linux")
    monkeypatch.setattr(subprocess_local.os, "killpg",
                        lambda _pid, _sig: (_ for _ in ()).throw(PermissionError()),
                        raising=False)
    monkeypatch.setattr(subprocess_local.os, "kill",
                        lambda pid, sig: delivered.append((pid, sig)))

    subprocess_local.signal_tree(123, "SIGTERM")

    assert delivered == [(123, subprocess_local.py_signal.SIGTERM)]


@pytest.mark.asyncio
async def test_terminal_ownership_survives_top_level_exit_until_quiescence():
    from dsh.subprocess import SubprocessTerminalSpawnSpec

    runtime = LocalSubprocessRuntime(Context())
    handle = await runtime.spawn_terminal(SubprocessTerminalSpawnSpec(
        argv=[sys.executable, "-c", "import time; time.sleep(0.05)"],
        cwd=os.getcwd(), rows=24, cols=80, grace_ms=100,
    ))
    terminate_started = asyncio.Event()
    release_terminate = asyncio.Event()
    original_terminate = handle.terminate

    async def controlled_terminate():
        terminate_started.set()
        await release_terminate.wait()
        await original_terminate()

    handle.terminate = controlled_terminate
    await handle.done
    await asyncio.sleep(0.02)

    try:
        assert terminate_started.is_set()
        assert handle in runtime.terminals
    finally:
        release_terminate.set()
        deadline = asyncio.get_event_loop().time() + 1
        while handle in runtime.terminals:
            assert asyncio.get_event_loop().time() < deadline
            await asyncio.sleep(0.01)
        if handle._proc.stdin is not None:
            handle._proc.stdin.close()
        if handle.output is not None:
            handle.output.close()
