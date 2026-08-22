import pytest
from dsh.core.consumed_work import fold_consumed_work, ConsumedWork


def test_fold_consumed_work_empty():
    res = fold_consumed_work([])
    assert res.end is None
    assert res.dropped_unrun is False


def test_fold_consumed_work_turn_completed():
    events = [
        {"type": "turn/start", "data": {"turn": 1}},
        {"type": "agent/inbox/spliced", "data": {"removedCount": 1, "inserted": []}},
        {"type": "step/start", "data": {"turn": 1, "step": 1}},
        {"type": "turn/end", "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]
    res = fold_consumed_work(events)
    assert res.end is not None
    assert res.end["data"]["turn"] == 1
    assert res.dropped_unrun is False


def test_fold_consumed_work_dropped_unrun():
    events = [
        {"type": "agent/inbox/spliced", "data": {"removedCount": 1, "inserted": [], "outcome": "canceled"}},
    ]
    res = fold_consumed_work(events)
    assert res.dropped_unrun is True
