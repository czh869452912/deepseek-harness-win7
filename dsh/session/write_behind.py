"""Per-session bounded writes, ported from the pinned SessionWriteBehind.

Python observers should shield shared flush futures when they can be cancelled.
The controller owns the write; cancelling an observer must not cancel durability.
"""
import asyncio
import copy
import inspect
from typing import Any, Callable, Dict, List, Optional


class SessionWriteBehind:
    def __init__(self, write: Callable, report_background_failure: Callable,
                 max_delay_ms: int = 200, loop: Optional[Any] = None):
        self.write = write
        self.report_background_failure = report_background_failure
        self.max_delay_ms = max_delay_ms
        self.loop = loop or asyncio.get_event_loop()
        self.pending: List[Dict[str, Any]] = []
        self.timer = None
        self.active = None
        self.barrier = None
        self.deadline_expired = False
        self.automatic_paused = False

    @property
    def has_work(self):
        return bool(self.pending) or self.active is not None

    def enqueue(self, event):
        was_empty = not self.pending
        self.pending.append(copy.deepcopy(event))
        if self.barrier is not None:
            return
        if self.automatic_paused:
            self.automatic_paused = False
            self.deadline_expired = False
            self._arm_timer()
        elif was_empty:
            self._arm_timer()

    def _arm_timer(self):
        self.timer = self.loop.call_later(self.max_delay_ms / 1000, self._on_deadline)

    def _cancel_timer(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None

    def cancel_automatic_wait(self):
        self._cancel_timer()
        self.deadline_expired = False

    def _on_deadline(self):
        self.timer = None
        if self.active is not None:
            self.deadline_expired = True
        else:
            self._start_background()

    def _start_background(self):
        active = self._start_write(True)
        def settled(job):
            if job.cancelled() or job.exception() is not None:
                return
            if self.barrier is None and self.pending and self.deadline_expired:
                self.deadline_expired = False
                self._start_background()
        active.add_done_callback(settled)

    def _start_write(self, background):
        batch, self.pending = self.pending, []
        self.cancel_automatic_wait()
        async def operation():
            try:
                result = self.write(batch)
                if inspect.isawaitable(result):
                    await result
            except BaseException as error:
                self.pending = batch + self.pending
                self.cancel_automatic_wait()
                self.automatic_paused = True
                if background:
                    self.report_background_failure(error)
                raise
            finally:
                self.active = None
        self.active = self.loop.create_task(operation())
        return self.active

    def flush(self):
        if self.barrier is not None:
            return self.barrier
        self.cancel_automatic_wait()
        self.automatic_paused = False
        barrier = self.loop.create_future()
        # JS drainBarrier executes its empty-path body before flush returns.
        if self.active is None and not self.pending:
            barrier.set_result(None)
            return barrier
        self.barrier = barrier
        async def drain():
            try:
                overlapping = self.active
                if overlapping is not None:
                    await asyncio.gather(overlapping, return_exceptions=True)
                    self.automatic_paused = False
                while self.pending:
                    await self._start_write(False)
            except BaseException as error:
                self.barrier = None
                if not barrier.done():
                    barrier.set_exception(error)
            else:
                self.barrier = None
                if not barrier.done():
                    barrier.set_result(None)
        self.loop.create_task(drain())
        return barrier
