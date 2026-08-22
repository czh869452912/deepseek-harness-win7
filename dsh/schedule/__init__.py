"""
Agent-scoped durable one-shot and fixed-rate reminders over the session event log.
1:1 parity with @deepseek-ai/dsh-schedule package.
Python 3.8.10 compatible.
"""

from typing import Any, Callable, Dict, List, Optional, Set

from dsh.cordis.plugin import Plugin
from dsh.schedule.domain import (
    allocate_schedule_id,
    canonicalize_time_zone,
    create_after_schedule_record,
    create_at_schedule_record,
    create_every_schedule_record,
    decode_schedule_change,
    fold_schedule_events,
    MIN_EVERY_INTERVAL_SECONDS,
    render_every_reminder_batch_framing,
    render_reminder_framing,
    resolve_every_occurrence,
    SCHEDULE_CHANGE_VERSION,
    ScheduleId,
    ScheduleInputError,
    ScheduleLogError,
    schedule_view,
)
from dsh.schedule.persistence import SchedulePersistenceError, flush_schedule_persistence
from dsh.schedule.runtime import ScheduleRuntime
from dsh.schedule.tools import register_schedule_tools
from dsh.schedule.types import (
    AfterScheduleRecord,
    AtScheduleRecord,
    EveryScheduleRecord,
    EveryOccurrence,
    FoldedSchedules,
    ScheduleRecord,
    ScheduleView,
)

name = "schedule"
inject = ["agents", "sessions", "tools", "sessionPersistence"]


def apply(ctx: Any) -> Callable[[], None]:
    """Install Schedule plugin for root agents published in context."""
    runtimes: Dict[Any, Callable[[], None]] = {}
    stopping = [False]

    def on_agent_created(data: Any) -> None:
        if stopping[0]:
            return
        agent = data.get("agent") if isinstance(data, dict) else getattr(data, "agent", None)
        if not agent or agent in runtimes:
            return

        agents_svc = ctx.get("agents") if hasattr(ctx, "get") and ctx.has("agents") else getattr(ctx, "agents", None)
        if agents_svc and hasattr(agents_svc, "roots"):
            roots = agents_svc.roots()
            if agent not in roots:
                return

        runtime = ScheduleRuntime(ctx, agent)
        agent_ctx = getattr(agent, "ctx", ctx)

        def request_drive_cb():
            runtime.request_drive()

        dispose_tools = register_schedule_tools(ctx, agent_ctx, agent, request_drive_cb)

        def on_agent_status(status_data: Any):
            status = status_data.get("status") if isinstance(status_data, dict) else getattr(status_data, "status", None)
            if status == "idle":
                events = getattr(agent.session, "events", [])
                if any((e.type if hasattr(e, "type") else e.get("type")) == "schedule/change" for e in events):
                    runtime.request_drive()

        stop_status = agent_ctx.on("agent/status", on_agent_status) if hasattr(agent_ctx, "on") else lambda: None
        runtime.start()

        def cleanup():
            stop_status()
            dispose_tools()
            if agent in runtimes:
                del runtimes[agent]

        runtimes[agent] = cleanup

    stop_created = ctx.on("agent/created", on_agent_created) if hasattr(ctx, "on") else lambda: None

    def unapply():
        stopping[0] = True
        stop_created()
        cleanups = list(runtimes.values())
        runtimes.clear()
        for c in cleanups:
            try:
                c()
            except Exception:
                pass

    if hasattr(ctx, "effect"):
        ctx.effect(unapply)

    return unapply


class SchedulePlugin(Plugin):
    """Cordis Plugin representation for Schedule service."""
    id = "schedule"
    name = "@deepseek-ai/dsh-schedule"
    inject = inject

    def apply(self, ctx: Any) -> None:
        apply(ctx)


__all__ = [
    "name",
    "inject",
    "apply",
    "SchedulePlugin",
    "ScheduleId",
    "ScheduleInputError",
    "ScheduleLogError",
    "SchedulePersistenceError",
    "SCHEDULE_CHANGE_VERSION",
    "MIN_EVERY_INTERVAL_SECONDS",
    "allocate_schedule_id",
    "create_after_schedule_record",
    "create_at_schedule_record",
    "create_every_schedule_record",
    "decode_schedule_change",
    "fold_schedule_events",
    "render_reminder_framing",
    "render_every_reminder_batch_framing",
    "resolve_every_occurrence",
    "schedule_view",
    "canonicalize_time_zone",
    "register_schedule_tools",
    "ScheduleRuntime",
    "flush_schedule_persistence",
    "AfterScheduleRecord",
    "AtScheduleRecord",
    "EveryScheduleRecord",
    "ScheduleRecord",
    "ScheduleView",
]
