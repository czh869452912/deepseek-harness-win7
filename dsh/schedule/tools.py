"""
Agent-scoped Schedule management tools over the durable session fold.
1:1 parity with @deepseek-ai/dsh-schedule/tools.ts
Python 3.8.10 compatible.
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional, Union

from dsh.schedule.domain import (
    allocate_schedule_id,
    create_after_schedule_record,
    create_at_schedule_record,
    create_every_schedule_record,
    fold_schedule_events,
    MIN_EVERY_INTERVAL_SECONDS,
    ScheduleId,
    ScheduleInputError,
    ScheduleLogError,
    schedule_view,
)
from dsh.schedule.persistence import flush_schedule_persistence
from dsh.schedule.transaction import run_schedule_transaction

CREATE_DESCRIPTION = (
    "Create one reminder in the current session. Supply a non-empty prompt and exactly one selector: "
    "a positive safe-integer after_seconds delay, at as a strict offset date-time or local "
    f"date/time object, or safe-integer every_seconds of at least {MIN_EVERY_INTERVAL_SECONDS}. "
    "Fixed-rate reminders stay creation-aligned, skip missed occurrences, and batch one latest "
    "occurrence per overdue rule. "
    "Delivery is session-local: the reminder runs on time only while this session "
    "is live and otherwise becomes overdue until the session is resumed."
)

LIST_DESCRIPTION = (
    "List every active reminder in the current session in creation order, including its exact id, "
    "UTC target, scheduled or overdue state, and session-local delivery mode."
)

DELETE_DESCRIPTION = (
    "Delete one active reminder in the current session by the exact id returned by schedule_create "
    "or schedule_list. Unknown or already-finished ids return deleted false."
)


def internal_error() -> Dict[str, str]:
    return {"code": "internal_error", "message": "The schedule operation failed."}


def corrupt_log_error() -> Dict[str, str]:
    return {"code": "corrupt_schedule_log", "message": "The session schedule log is corrupt."}


def persistence_error(operation: str, id: Optional[str] = None) -> Dict[str, Any]:
    res: Dict[str, Any] = {
        "code": "persistence_uncertain",
        "message": "Schedule persistence is uncertain; retry with schedule_list before relying on this result.",
        "operation": operation,
    }
    if id is not None:
        res["id"] = id
    return res


def input_error(error: ScheduleInputError) -> Dict[str, str]:
    return {"code": error.code, "message": error.message}


def fold_for_tool(agent: Any) -> Union[Any, Dict[str, str]]:
    try:
        events = getattr(agent.session, "events", [])
        header = getattr(agent.session, "header", None)
        seed_length = getattr(header, "seedLength", 0) if header else 0
        return fold_schedule_events(events, seed_length)
    except Exception as e:
        if isinstance(e, ScheduleLogError):
            return corrupt_log_error()
        return internal_error()


def is_tool_error(value: Any) -> bool:
    return isinstance(value, dict) and "code" in value


async def preflight(
    root_ctx: Any, agent: Any, operation: str, id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    try:
        await flush_schedule_persistence(root_ctx, agent.session)
        return None
    except Exception:
        return persistence_error(operation, id)


def validate_create_args(args: Dict[str, Any]) -> Optional[Dict[str, str]]:
    allowed_keys = {"prompt", "after_seconds", "every_seconds", "at"}
    if not set(args.keys()).issubset(allowed_keys):
        return {
            "code": "invalid_selector",
            "message": "schedule_create accepts exactly one of after_seconds, at, or every_seconds.",
        }

    has_after = "after_seconds" in args and args["after_seconds"] is not None
    has_at = "at" in args and args["at"] is not None
    has_every = "every_seconds" in args and args["every_seconds"] is not None

    count = int(has_after) + int(has_at) + int(has_every)
    if count != 1:
        return {
            "code": "invalid_selector",
            "message": "schedule_create accepts exactly one of after_seconds, at, or every_seconds.",
        }

    prompt = args.get("prompt")
    if not isinstance(prompt, str) or len(prompt.strip()) == 0:
        return {"code": "invalid_prompt", "message": "prompt must be non-empty after trimming."}

    if has_after:
        after_sec = args["after_seconds"]
        if not isinstance(after_sec, int) or isinstance(after_sec, bool) or after_sec <= 0:
            return {"code": "invalid_rule", "message": "after_seconds must be a positive safe integer."}

    if has_every:
        every_sec = args["every_seconds"]
        if not isinstance(every_sec, int) or isinstance(every_sec, bool):
            return {"code": "invalid_rule", "message": "every_seconds must be a safe integer."}
        if every_sec < MIN_EVERY_INTERVAL_SECONDS:
            return {
                "code": "frequency_too_high",
                "message": f"every_seconds must be at least {MIN_EVERY_INTERVAL_SECONDS}.",
            }

    return None


def register_schedule_tools(
    root_ctx: Any,
    tool_ctx: Any,
    agent: Any,
    on_durable_change: Callable[[], None],
) -> Callable[[], None]:
    disposers: List[Callable[[], None]] = []

    def notify_durable_change():
        try:
            on_durable_change()
        except Exception:
            pass

    tools_svc = tool_ctx.get("tools") if hasattr(tool_ctx, "get") and tool_ctx.has("tools") else getattr(tool_ctx, "tools", None)
    if not tools_svc:
        return lambda: None

    # 1. schedule_create
    async def exec_schedule_create(args: Dict[str, Any], **kwargs) -> Any:
        full_args = dict(args) if isinstance(args, dict) else kwargs
        if "prompt" not in full_args and "prompt" in kwargs:
            full_args["prompt"] = kwargs["prompt"]

        invalid = validate_create_args(full_args)
        if invalid is not None:
            return invalid

        async def _do_create():
            uncertain = await preflight(root_ctx, agent, "create")
            if uncertain is not None:
                return uncertain
            notify_durable_change()

            folded = fold_for_tool(agent)
            if is_tool_error(folded):
                return folded

            sched_id = allocate_schedule_id(folded)
            now_ms = int(time.time() * 1000)
            prompt = full_args["prompt"]

            try:
                if full_args.get("at") is not None:
                    record = create_at_schedule_record(sched_id, prompt, full_args["at"], now_ms)
                elif full_args.get("after_seconds") is not None:
                    record = create_after_schedule_record(sched_id, prompt, full_args["after_seconds"], now_ms)
                else:
                    record = create_every_schedule_record(sched_id, prompt, full_args["every_seconds"], now_ms)
            except Exception as e:
                if isinstance(e, ScheduleInputError):
                    return input_error(e)
                return internal_error()

            try:
                agent.session.append(
                    "schedule/change",
                    {
                        "version": 1,
                        "operation": "create",
                        "schedule": record.to_dict(),
                    },
                )
            except Exception:
                return internal_error()

            barrier = await preflight(root_ctx, agent, "create", sched_id)
            if barrier is not None:
                return barrier
            notify_durable_change()
            return schedule_view(record, int(time.time() * 1000)).to_dict()

        return await run_schedule_transaction(agent, _do_create)

    # 2. schedule_list
    async def exec_schedule_list(args: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        async def _do_list():
            uncertain = await preflight(root_ctx, agent, "list")
            if uncertain is not None:
                return uncertain
            notify_durable_change()

            folded = fold_for_tool(agent)
            if is_tool_error(folded):
                return folded

            now_ms = int(time.time() * 1000)
            return [schedule_view(rec, now_ms).to_dict() for rec in folded.active]

        return await run_schedule_transaction(agent, _do_list)

    # 3. schedule_delete
    async def exec_schedule_delete(args: Dict[str, Any], **kwargs) -> Any:
        full_args = dict(args) if isinstance(args, dict) else kwargs
        id_val = full_args.get("id") or kwargs.get("id", "")
        if not isinstance(id_val, str) or len(id_val) == 0 or id_val.strip() != id_val:
            return {
                "code": "invalid_rule",
                "message": "schedule_delete id must be non-empty without surrounding whitespace.",
            }

        async def _do_delete():
            uncertain = await preflight(root_ctx, agent, "delete", id_val)
            if uncertain is not None:
                return uncertain
            notify_durable_change()

            folded = fold_for_tool(agent)
            if is_tool_error(folded):
                return folded

            if not any(rec.id == id_val for rec in folded.active):
                return {"id": id_val, "deleted": False, "code": "schedule_not_found"}

            try:
                agent.session.append(
                    "schedule/change",
                    {"version": 1, "operation": "delete", "id": id_val},
                )
            except Exception:
                return internal_error()

            barrier = await preflight(root_ctx, agent, "delete", id_val)
            if barrier is not None:
                return barrier
            notify_durable_change()
            return {"id": id_val, "deleted": True}

        return await run_schedule_transaction(agent, _do_delete)

    # Register tools
    d1 = tools_svc.register({
        "name": "schedule_create",
        "description": CREATE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Reminder content to present when due."},
                "after_seconds": {"type": "integer", "description": "Positive delay in seconds."},
                "every_seconds": {"type": "integer", "description": f"Fixed-rate interval, at least {MIN_EVERY_INTERVAL_SECONDS}."},
                "at": {
                    "description": "Absolute target as string RFC 3339 or local date/time object.",
                },
            },
            "required": ["prompt"],
        },
        "execute": exec_schedule_create,
        "handler": exec_schedule_create,
    })
    disposers.append(d1)

    d2 = tools_svc.register({
        "name": "schedule_list",
        "description": LIST_DESCRIPTION,
        "parameters": {"type": "object", "properties": {}},
        "execute": exec_schedule_list,
        "handler": exec_schedule_list,
    })
    disposers.append(d2)

    d3 = tools_svc.register({
        "name": "schedule_delete",
        "description": DELETE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Exact session-local schedule id."}
            },
            "required": ["id"],
        },
        "execute": exec_schedule_delete,
        "handler": exec_schedule_delete,
    })
    disposers.append(d3)

    def dispose_all():
        for d in reversed(disposers):
            try:
                d()
            except Exception:
                pass

    return dispose_all
