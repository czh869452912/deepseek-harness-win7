"""
Durable and model-facing Schedule value types.
1:1 parity with @deepseek-ai/dsh-schedule/types.ts
Python 3.8.10 compatible.
"""

from typing import Any, Dict, List, Optional, Union

ScheduleId = str

class AfterScheduleRecord:
    def __init__(self, id: str, prompt: str, after_seconds: int, scheduled_at: str):
        self.id = id
        self.kind = "after"
        self.prompt = prompt
        self.afterSeconds = after_seconds
        self.scheduledAt = scheduled_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "prompt": self.prompt,
            "afterSeconds": self.afterSeconds,
            "scheduledAt": self.scheduledAt,
        }


class AtScheduleRecord:
    def __init__(self, id: str, prompt: str, scheduled_at: str):
        self.id = id
        self.kind = "at"
        self.prompt = prompt
        self.scheduledAt = scheduled_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "prompt": self.prompt,
            "scheduledAt": self.scheduledAt,
        }


class EveryScheduleRecord:
    def __init__(self, id: str, prompt: str, every_seconds: int, scheduled_at: str):
        self.id = id
        self.kind = "every"
        self.prompt = prompt
        self.everySeconds = every_seconds
        self.scheduledAt = scheduled_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "prompt": self.prompt,
            "everySeconds": self.everySeconds,
            "scheduledAt": self.scheduledAt,
        }


ScheduleRecord = Union[AfterScheduleRecord, AtScheduleRecord, EveryScheduleRecord]


class LocalAtInput:
    def __init__(self, date: str, time: str, time_zone: str):
        self.date = date
        self.time = time
        self.time_zone = time_zone


class ScheduleView:
    def __init__(self, record: ScheduleRecord, state: str, delivery_mode: str = "session-local"):
        self.record = record
        self.id = record.id
        self.kind = record.kind
        self.prompt = record.prompt
        self.scheduledAt = record.scheduledAt
        self.state = state
        self.deliveryMode = delivery_mode
        if hasattr(record, "afterSeconds"):
            self.afterSeconds = getattr(record, "afterSeconds")
        if hasattr(record, "everySeconds"):
            self.everySeconds = getattr(record, "everySeconds")

    def to_dict(self) -> Dict[str, Any]:
        res = self.record.to_dict()
        res["state"] = self.state
        res["deliveryMode"] = self.deliveryMode
        return res


class FoldedSchedules:
    def __init__(self, active: List[ScheduleRecord], seen_ids: List[str]):
        self.active = active
        self.seenIds = seen_ids


class EveryOccurrence:
    def __init__(self, occurrence_at: str, next_scheduled_at: Optional[str] = None):
        self.occurrenceAt = occurrence_at
        self.nextScheduledAt = next_scheduled_at
