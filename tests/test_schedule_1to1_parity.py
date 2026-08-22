"""
Unit tests for dsh.schedule 1:1 parity with @deepseek-ai/dsh-schedule.
"""

import asyncio
import time
import pytest

from dsh.cordis.context import Context
from dsh.schedule import (
    allocate_schedule_id,
    apply as apply_schedule,
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
    SchedulePlugin,
    ScheduleRuntime,
    register_schedule_tools,
    AfterScheduleRecord,
    AtScheduleRecord,
    EveryScheduleRecord,
)


class MockSession:
    def __init__(self):
        self.events = []
        self.header = type("Header", (), {"seedLength": 0})()

    def append(self, type_name: str, data: dict, ignorable: bool = False):
        class Event:
            pass
        e = Event()
        e.type = type_name
        e.data = data
        self.events.append(e)


class MockAgent:
    def __init__(self, agent_id: str = "root-agent"):
        self.id = agent_id
        self.session = MockSession()
        self.ctx = Context()
        self.followups = []

    def followup(self, message):
        self.followups.append(message)

    async def run_maintenance(self, fn):
        return await fn()


@pytest.mark.asyncio
async def test_schedule_domain_records_and_folding():
    now_ms = 1700000000000

    # 1. create_after_schedule_record
    rec_after = create_after_schedule_record("schedule-1", "Check build", 300, now_ms)
    assert rec_after.kind == "after"
    assert rec_after.prompt == "Check build"
    assert rec_after.afterSeconds == 300

    # 2. create_every_schedule_record
    rec_every = create_every_schedule_record("schedule-2", "Recurring check", 600, now_ms)
    assert rec_every.kind == "every"
    assert rec_every.everySeconds == 600

    # Invalid prompt
    with pytest.raises(ScheduleInputError) as exc_info:
        create_after_schedule_record("schedule-3", "   ", 300, now_ms)
    assert exc_info.value.code == "invalid_prompt"

    # Frequency too high
    with pytest.raises(ScheduleInputError) as exc_info:
        create_every_schedule_record("schedule-3", "Too fast", 100, now_ms)
    assert exc_info.value.code == "frequency_too_high"

    # Fold events
    session = MockSession()
    session.append("schedule/change", {"version": 1, "operation": "create", "schedule": rec_after.to_dict()})
    session.append("schedule/change", {"version": 1, "operation": "create", "schedule": rec_every.to_dict()})

    folded = fold_schedule_events(session.events)
    assert len(folded.active) == 2
    assert folded.seenIds == ["schedule-1", "schedule-2"]

    new_id = allocate_schedule_id(folded)
    assert new_id == "schedule-3"


@pytest.mark.asyncio
async def test_schedule_occurrence_resolution():
    now_ms = 1700000000000
    rec_every = create_every_schedule_record("schedule-1", "Task", 600, now_ms)
    scheduled_at_ms = parse_utc_instant(rec_every.scheduledAt)

    # Resolve occurrence 1200 seconds later (2 periods)
    future_now_ms = scheduled_at_ms + 1200 * 1000
    occ = resolve_every_occurrence(rec_every, future_now_ms)
    assert occ.occurrenceAt is not None
    assert occ.nextScheduledAt is not None


def parse_utc_instant(instant_str: str) -> int:
    from dsh.schedule.domain import parse_utc_instant as p
    return p(instant_str)


@pytest.mark.asyncio
async def test_schedule_tools():
    ctx = Context()
    tools_svc = type("ToolsService", (), {"_tools": {}})()

    def register(spec):
        name = spec["name"]

        async def handler(*args, **kwargs):
            return await spec["execute"](*args, **kwargs)

        tools_svc._tools[name] = handler
        return lambda: tools_svc._tools.pop(name, None)

    tools_svc.register = register
    ctx.set_service("tools", tools_svc)

    agent = MockAgent()
    disposer = register_schedule_tools(ctx, ctx, agent, lambda: None)

    # 1. schedule_create
    create_fn = tools_svc._tools["schedule_create"]
    res_create = await create_fn(args={"prompt": "Do task", "after_seconds": 600})
    assert res_create["id"] == "schedule-1"
    assert res_create["kind"] == "after"
    assert res_create["prompt"] == "Do task"

    # 2. schedule_list
    list_fn = tools_svc._tools["schedule_list"]
    res_list = await list_fn(args={})
    assert len(res_list) == 1
    assert res_list[0]["id"] == "schedule-1"

    # 3. schedule_delete
    delete_fn = tools_svc._tools["schedule_delete"]
    res_del = await delete_fn(args={"id": "schedule-1"})
    assert res_del == {"id": "schedule-1", "deleted": True}

    res_list_after_del = await list_fn(args={})
    assert len(res_list_after_del) == 0

    disposer()


@pytest.mark.asyncio
async def test_schedule_runtime_drive():
    ctx = Context()
    agent = MockAgent()

    # Stub agents service
    class AgentsService:
        def roots(self):
            return [agent]

    ctx.set_service("agents", AgentsService())

    runtime = ScheduleRuntime(ctx, agent)
    runtime.start()

    # Append past due schedule event
    past_ms = int(time.time() * 1000) - 10000
    rec = AfterScheduleRecord(id="schedule-1", prompt="Overdue reminder", after_seconds=10, scheduled_at="2020-01-01T00:00:00.000Z")
    agent.session.append("schedule/change", {"version": 1, "operation": "create", "schedule": rec.to_dict()})

    runtime.request_drive()
    await asyncio.sleep(0.1)

    assert len(agent.followups) == 1
    assert "[SCHEDULE REMINDER]" in agent.followups[0]["content"][0]["text"]
    assert "Overdue reminder" in agent.followups[0]["content"][0]["text"]

    await runtime.dispose()
