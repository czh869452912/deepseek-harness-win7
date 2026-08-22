"""
Disposable live timer projection for one exact root agent.
1:1 parity with @deepseek-ai/dsh-schedule/runtime.ts
Python 3.8.10 compatible.
"""

asyncio = __import__("asyncio")
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from dsh.schedule.domain import (
    fold_schedule_events,
    parse_utc_instant,
    render_every_reminder_batch_framing,
    render_reminder_framing,
    resolve_every_occurrence,
    ScheduleLogError,
    FoldedSchedules,
)
from dsh.schedule.persistence import flush_schedule_persistence
from dsh.schedule.transaction import run_schedule_transaction
from dsh.schedule.types import EveryScheduleRecord, ScheduleRecord

MAX_TIMER_DELAY_MS = 2147483647
logger = logging.getLogger("dsh.schedule")


class DueDecision:
    def __init__(
        self,
        kind: str,  # "one-shot" | "every" | "wait"
        record: Optional[ScheduleRecord] = None,
        reminders: Optional[List[Dict[str, Any]]] = None,
        accepted_at: Optional[str] = None,
        target: Optional[int] = None,
    ):
        self.kind = kind
        self.record = record
        self.reminders = reminders or []
        self.acceptedAt = accepted_at
        self.target = target


def due_decision(folded: FoldedSchedules, now: int) -> DueDecision:
    indexed = [(record, index) for index, record in enumerate(folded.active)]

    def sort_key(entry):
        rec, idx = entry
        return (parse_utc_instant(rec.scheduledAt), idx)

    one_shots = [
        (rec, idx)
        for rec, idx in indexed
        if rec.kind != "every" and parse_utc_instant(rec.scheduledAt) <= now
    ]
    if one_shots:
        one_shots.sort(key=sort_key)
        return DueDecision(kind="one-shot", record=one_shots[0][0])

    everys = [
        (rec, idx)
        for rec, idx in indexed
        if rec.kind == "every" and parse_utc_instant(rec.scheduledAt) <= now
    ]
    if everys:
        everys.sort(key=sort_key)
        now_dt_str = datetime_to_iso(now)
        reminders = [
            {
                "record": rec,
                "occurrenceAt": resolve_every_occurrence(rec, now).occurrenceAt,
            }
            for rec, _ in everys
        ]
        return DueDecision(kind="every", reminders=reminders, accepted_at=now_dt_str)

    future_targets = [
        parse_utc_instant(rec.scheduledAt)
        for rec in folded.active
        if parse_utc_instant(rec.scheduledAt) > now
    ]
    if future_targets:
        return DueDecision(kind="wait", target=min(future_targets))
    return DueDecision(kind="wait", target=None)


def datetime_to_iso(now_ms: int) -> str:
    from dsh.schedule.domain import ms_to_utc_instant
    return ms_to_utc_instant(now_ms)


class ScheduleRuntime:
    """One process-local, disposable projection of an exact agent's durable schedules."""

    def __init__(self, ctx: Any, agent: Any):
        self.ctx = ctx
        self.agent = agent
        self.timer_handle: Optional[Any] = None
        self.run_task: Optional[asyncio.Task] = None
        self.requested = False
        self.stopping = False
        self.faulted = False
        self.idle_wait_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.request_drive()

    def request_drive(self) -> None:
        if self.stopping or self.faulted:
            return
        self.clear_timer()
        self.requested = True
        if self.run_task is not None and not self.run_task.done():
            return

        try:
            loop = asyncio.get_event_loop()
            self.run_task = loop.create_task(self._run_requested())
        except Exception as e:
            if self._is_live():
                logger.warning(f"schedule: could not start runtime for agent '{getattr(self.agent, 'id', '')}': {e}")
            return

    async def dispose(self) -> None:
        self.stopping = True
        self.requested = False
        self.clear_timer()
        if self.run_task is not None and not self.run_task.done():
            self.run_task.cancel()
        if self.idle_wait_task is not None and not self.idle_wait_task.done():
            self.idle_wait_task.cancel()

    async def _run_requested(self) -> None:
        try:
            while self.requested and not self.stopping and not self.faulted:
                self.requested = False
                await run_schedule_transaction(self.agent, self._drive_once)
        except Exception as e:
            if self._is_live():
                logger.warning(f"schedule: runtime failed for agent '{getattr(self.agent, 'id', '')}': {e}")
            self.faulted = True
        finally:
            self.run_task = None
            if self.requested and not self.stopping and not self.faulted:
                self.request_drive()

    def _is_live(self) -> bool:
        agents_svc = self.ctx.get("agents") if hasattr(self.ctx, "get") and self.ctx.has("agents") else getattr(self.ctx, "agents", None)
        if not agents_svc:
            return True
        if hasattr(agents_svc, "roots"):
            roots = agents_svc.roots()
            return self.agent in roots
        return True

    def _is_runnable(self) -> bool:
        return not self.stopping and self._is_live()

    def clear_timer(self) -> None:
        if self.timer_handle is not None:
            self.timer_handle.cancel()
            self.timer_handle = None

    def _arm(self, target_ms: int, now_ms: int) -> None:
        delay_ms = min(target_ms - now_ms, MAX_TIMER_DELAY_MS)
        delay_sec = max(0.0, delay_ms / 1000.0)
        loop = asyncio.get_event_loop()
        self.timer_handle = loop.call_later(delay_sec, self.request_drive)

    def _read_folded(self) -> Optional[FoldedSchedules]:
        try:
            events = getattr(self.agent.session, "events", [])
            header = getattr(self.agent.session, "header", None)
            seed_length = getattr(header, "seedLength", 0) if header else 0
            return fold_schedule_events(events, seed_length)
        except Exception as e:
            self.faulted = True
            detail = e.message if isinstance(e, ScheduleLogError) else str(e)
            logger.warning(f"schedule: corrupt schedule log for agent '{getattr(self.agent, 'id', '')}': {detail}")
            return None

    def _decide(self, folded: FoldedSchedules, now_ms: int) -> Optional[DueDecision]:
        try:
            return due_decision(folded, now_ms)
        except Exception as e:
            logger.warning(f"schedule: fixed-rate decision failed for agent '{getattr(self.agent, 'id', '')}': {e}")
            return None

    async def _drive_once(self) -> None:
        self.clear_timer()
        if not self._is_runnable():
            return

        try:
            await flush_schedule_persistence(self.ctx, self.agent.session)
        except Exception as e:
            if self._is_live():
                logger.warning(f"schedule: preflight failed for agent '{getattr(self.agent, 'id', '')}': {e}")
            return

        if not self._is_runnable():
            return

        folded = self._read_folded()
        if folded is None:
            return

        now_ms = int(time.time() * 1000)
        decision = self._decide(folded, now_ms)
        if decision is None:
            return

        if decision.kind == "wait":
            if decision.target is not None:
                self._arm(decision.target, now_ms)
            return

        # Maintenance execution
        async def do_maintenance():
            if not self._is_runnable():
                return False
            claimed = self._read_folded()
            if claimed is None:
                return False
            decision_now = int(time.time() * 1000)
            d = self._decide(claimed, decision_now)
            if d is None:
                return False
            if d.kind == "wait":
                if d.target is not None:
                    self._arm(d.target, decision_now)
                return False

            try:
                if d.kind == "one-shot":
                    text = render_reminder_framing(d.record)
                else:
                    text = render_every_reminder_batch_framing(d.reminders)

                message = {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                    "source": {"kind": "plugin", "plugin": "schedule"},
                }

                if hasattr(self.agent, "followup"):
                    self.agent.followup(message)
                elif hasattr(self.agent, "inject_user_message"):
                    self.agent.inject_user_message(message)
            except Exception as e:
                if self._is_live():
                    logger.warning(f"schedule: framing or followup failed for agent '{getattr(self.agent, 'id', '')}': {e}")
                return False

            try:
                if d.kind == "one-shot":
                    self.agent.session.append(
                        "schedule/change",
                        {"version": 1, "operation": "dispatch", "id": d.record.id},
                    )
                else:
                    for rem in d.reminders:
                        self.agent.session.append(
                            "schedule/change",
                            {
                                "version": 1,
                                "operation": "dispatch",
                                "id": rem["record"].id,
                                "acceptedAt": d.acceptedAt,
                            },
                        )
            except Exception as e:
                self.faulted = True
                self.clear_timer()
                logger.warning(f"schedule: dispatch append failed for agent '{getattr(self.agent, 'id', '')}': {e}")
                return False

            return True

        if hasattr(self.agent, "run_maintenance"):
            try:
                m_res = await self.agent.run_maintenance(do_maintenance)
            except Exception:
                return
        else:
            m_res = await do_maintenance()

        if not m_res:
            return

        try:
            await flush_schedule_persistence(self.ctx, self.agent.session)
        except Exception as e:
            if self._is_live():
                logger.warning(f"schedule: dispatch barrier failed for agent '{getattr(self.agent, 'id', '')}': {e}")
            return

        if self._is_runnable():
            self.request_drive()
