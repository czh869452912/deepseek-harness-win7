"""
Bounded, escalating process shutdown for the long-lived CLI surfaces.
Matching reference/apps/cli/src/process-shutdown.ts 1:1.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import sys
from typing import Any, Callable, Optional

PROCESS_SHUTDOWN_TIMEOUT_MS = 5000


class ProcessShutdown:
    """Process-exit controller shared by normal completion and signal handlers."""

    def __init__(
        self,
        dispose: Callable[[], Any],
        force_exit: Optional[Callable[[int], None]] = None,
        complete: Optional[Callable[[int], None]] = None,
        timeout_ms: int = PROCESS_SHUTDOWN_TIMEOUT_MS,
    ):
        self._dispose = dispose
        self._force_exit = force_exit if force_exit is not None else (lambda code: sys.exit(code))
        self._complete = complete if complete is not None else (lambda code: setattr(sys, "exitcode", code))
        self._timeout_ms = timeout_ms

        self._pending: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.TimerHandle] = None
        self._completed = False
        self._force_exited = False

    def _clear_exit_timeout(self) -> None:
        if self._timeout_task is not None:
            try:
                self._timeout_task.cancel()
            except Exception:
                pass
            self._timeout_task = None

    def _force_exit_once(self, code: int) -> None:
        if self._force_exited:
            return
        self._force_exited = True
        self._clear_exit_timeout()
        self._force_exit(code)

    def _complete_once(self, code: int) -> None:
        if self._completed or self._force_exited:
            return
        self._completed = True
        self._clear_exit_timeout()
        self._complete(code)

    async def _run_start(self, code: int, force_after_dispose: bool) -> None:
        loop = asyncio.get_running_loop()
        self._timeout_task = loop.call_later(self._timeout_ms / 1000.0, lambda: self._force_exit_once(code))
        try:
            res = self._dispose()
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                await res
            if force_after_dispose:
                self._force_exit_once(code)
            else:
                self._complete_once(code)
        except Exception:
            self._force_exit_once(code)

    async def shutdown(self, code: int = 0) -> None:
        """Start or join graceful disposal before allowing natural completion with `code`."""
        if self._pending is not None:
            await self._pending
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._run_start(code, False))
        self._pending = task
        await task

    def interrupt(self, code: int = 130) -> None:
        """Start graceful disposal followed by exit, or force exit when shutdown is already running."""
        if self._pending is not None:
            self._force_exit_once(code)
            return
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._run_start(code, True))
            self._pending = task
        except RuntimeError:
            self._force_exit_once(code)


def create_process_shutdown(
    dispose: Callable[[], Any],
    force_exit: Optional[Callable[[int], None]] = None,
    complete: Optional[Callable[[int], None]] = None,
    timeout_ms: int = PROCESS_SHUTDOWN_TIMEOUT_MS,
) -> ProcessShutdown:
    """Create one process-exit controller around an application disposer."""
    return ProcessShutdown(dispose, force_exit, complete, timeout_ms)


createProcessShutdown = create_process_shutdown
