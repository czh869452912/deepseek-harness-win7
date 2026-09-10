"""
1:1 unit tests for ProcessShutdown matching reference/apps/cli/tests/process-shutdown.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
from typing import Any, Callable, Dict, List
import pytest

from dsh.boot.process_shutdown import (
    create_process_shutdown,
    PROCESS_SHUTDOWN_TIMEOUT_MS,
    ProcessShutdown,
)


class Deferred:
    def __init__(self):
        self.future = asyncio.Future()

    def resolve(self):
        if not self.future.done():
            self.future.set_result(None)

    def reject(self, error: Exception):
        if not self.future.done():
            self.future.set_exception(error)

    async def promise(self):
        await self.future


@pytest.mark.asyncio
async def test_completes_naturally_after_disposal_resolves_and_forces_exit_when_rejects():
    resolved_exit: List[int] = []
    resolved_complete: List[int] = []

    async def _resolve_disp():
        pass

    resolved = create_process_shutdown(
        _resolve_disp,
        force_exit=lambda code: resolved_exit.append(code),
        complete=lambda code: resolved_complete.append(code),
    )
    await resolved.shutdown(0)
    assert len(resolved_complete) == 1
    assert resolved_complete[0] == 0
    assert len(resolved_exit) == 0
    assert resolved.exit_code == 0

    rejected_exit: List[int] = []
    rejected_complete: List[int] = []

    async def _reject_disp():
        raise RuntimeError("dispose failed")

    rejected = create_process_shutdown(
        _reject_disp,
        force_exit=lambda code: rejected_exit.append(code),
        complete=lambda code: rejected_complete.append(code),
    )
    await rejected.shutdown(1)
    assert len(rejected_exit) == 1
    assert rejected_exit[0] == 1
    assert len(rejected_complete) == 0
    assert rejected.exit_code == 1


@pytest.mark.asyncio
async def test_uses_exitcode_for_default_normal_completion():
    exits: List[int] = []
    shutdown = create_process_shutdown(lambda: asyncio.sleep(0.01), force_exit=lambda c: exits.append(c))
    await shutdown.shutdown(7)
    assert shutdown.exit_code == 7
    assert len(exits) == 0


@pytest.mark.asyncio
async def test_forces_exit_when_graceful_disposal_reaches_bound():
    disposal = Deferred()
    exit_calls: List[int] = []
    complete_calls: List[int] = []

    shutdown = create_process_shutdown(
        disposal.promise,
        force_exit=lambda c: exit_calls.append(c),
        complete=lambda c: complete_calls.append(c),
        timeout_ms=50,  # short 50ms timeout for test
    )

    task = shutdown.shutdown(0)
    await asyncio.sleep(0.02)
    assert len(exit_calls) == 0

    await asyncio.sleep(0.05)
    assert len(exit_calls) == 1
    assert exit_calls[0] == 0

    disposal.resolve()
    await task
    assert len(exit_calls) == 1
    assert len(complete_calls) == 0


@pytest.mark.asyncio
async def test_honors_caller_supplied_grace_period():
    disposal = Deferred()
    exit_calls: List[int] = []

    shutdown = create_process_shutdown(
        disposal.promise,
        force_exit=lambda c: exit_calls.append(c),
        complete=lambda c: None,
        timeout_ms=30,
    )
    task = shutdown.shutdown(0)
    await asyncio.sleep(0.01)
    assert len(exit_calls) == 0

    await asyncio.sleep(0.03)
    assert len(exit_calls) == 1

    disposal.resolve()
    await task


@pytest.mark.asyncio
async def test_lets_ctrl_c_force_normal_shutdown_already_stuck_in_disposal():
    disposal = Deferred()
    exit_calls: List[int] = []
    complete_calls: List[int] = []

    shutdown = create_process_shutdown(
        disposal.promise,
        force_exit=lambda c: exit_calls.append(c),
        complete=lambda c: complete_calls.append(c),
    )
    task = shutdown.shutdown(0)

    shutdown.interrupt(130)
    assert len(exit_calls) == 1
    assert exit_calls[0] == 130

    disposal.resolve()
    await task
    assert len(exit_calls) == 1
    assert len(complete_calls) == 0


@pytest.mark.asyncio
async def test_forces_exit_after_disposal_started_by_signal():
    disposal = Deferred()
    exit_calls: List[int] = []
    complete_calls: List[int] = []

    shutdown = create_process_shutdown(
        disposal.promise,
        force_exit=lambda c: exit_calls.append(c),
        complete=lambda c: complete_calls.append(c),
    )

    shutdown.interrupt(143)
    disposal.resolve()
    await shutdown.shutdown(0)

    assert len(exit_calls) == 1
    assert exit_calls[0] == 143
    assert len(complete_calls) == 0


@pytest.mark.asyncio
async def test_drains_on_first_signal_and_forces_on_second_signal():
    disposal = Deferred()
    dispose_called = []

    async def _disp():
        dispose_called.append(1)
        await disposal.promise()

    exit_calls: List[int] = []
    shutdown = create_process_shutdown(
        _disp,
        force_exit=lambda c: exit_calls.append(c),
        complete=lambda c: None,
    )

    shutdown.interrupt(143)
    await asyncio.sleep(0.01)
    assert len(dispose_called) == 1
    assert len(exit_calls) == 0

    shutdown.interrupt(130)
    assert len(exit_calls) == 1
    assert exit_calls[0] == 130

    disposal.resolve()
    await shutdown.shutdown(0)
    assert len(exit_calls) == 1


@pytest.mark.asyncio
async def test_coalesces_normal_shutdown_calls_without_treating_as_escalation():
    disposal = Deferred()
    exit_calls: List[int] = []
    complete_calls: List[int] = []

    shutdown = create_process_shutdown(
        disposal.promise,
        force_exit=lambda c: exit_calls.append(c),
        complete=lambda c: complete_calls.append(c),
    )

    first = shutdown.shutdown(0)
    second = shutdown.shutdown(1)
    assert second is first
    assert len(exit_calls) == 0

    disposal.resolve()
    await first
    assert len(complete_calls) == 1
    assert complete_calls[0] == 0
    assert len(exit_calls) == 0


@pytest.mark.asyncio
async def test_wait_method_returns_exit_code():
    shutdown = create_process_shutdown(
        lambda: asyncio.sleep(0.01),
        complete=lambda c: None,
    )
    shutdown.shutdown(42)
    code = await shutdown.wait()
    assert code == 42
    assert shutdown.exit_code == 42
