"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent/consumed-work
matching reference/packages/core/agent/tests/consumed-work.spec.ts
"""

import pytest
from dsh.core.consumed_work import fold_consumed_work, ConsumedWork
from dsh.core.session import Session


def message(text: str):
    return {"role": "user", "content": [{"type": "text", "text": text}], "source": {"kind": "user"}}


def accept(session: Session, text: str):
    session.append("agent/inbox/spliced", {"target": "next-turn", "start": 0, "inserted": [message(text)]})


def claim(session: Session):
    session.append("agent/inbox/spliced", {"target": "next-turn", "start": 0, "removedCount": 1, "inserted": []})


def cancel_pending(session: Session):
    session.append("agent/inbox/spliced", {
        "target": "next-turn", "start": 0, "removedCount": 1, "inserted": [], "outcome": "canceled",
    })


def stepped_turn(session: Session, turn: int, reason: dict):
    session.append("turn/start", {"turn": turn})
    claim(session)
    session.append("step/start", {"turn": turn, "step": 1})
    session.append("step/end", {"turn": turn, "step": 1})
    session.append("turn/end", {"turn": turn, "reason": reason})


def test_fold_consumed_work_empty_and_unconsumed():
    session = Session.create("empty")
    accept(session, "queued")
    res = fold_consumed_work(session.events)
    assert res.end is None
    assert res.dropped_unrun is False


def test_fold_consumed_work_stepped_turn_latest():
    session = Session.create("stepped")
    stepped_turn(session, 1, {"kind": "completed"})
    stepped_turn(session, 2, {"kind": "max-tokens"})

    res = fold_consumed_work(session.events)
    assert res.end is not None
    assert res.end["data"] == {"turn": 2, "reason": {"kind": "max-tokens"}}


def test_fold_consumed_work_failed_claim_without_step():
    session = Session.create("failed-claim")
    stepped_turn(session, 1, {"kind": "completed"})
    session.append("turn/start", {"turn": 2})
    claim(session)
    session.append("turn/end", {"turn": 2, "reason": {"kind": "error", "error": {"message": "ENOSPC", "code": "UNKNOWN"}}})

    res = fold_consumed_work(session.events)
    assert res.end["data"]["turn"] == 2


def test_fold_consumed_work_stopped_claim_without_step():
    session = Session.create("stopped-claim")
    stepped_turn(session, 1, {"kind": "completed"})
    session.append("turn/start", {"turn": 2})
    claim(session)
    session.append("turn/end", {"turn": 2, "reason": {"kind": "aborted", "reason": {"kind": "user"}}})

    res = fold_consumed_work(session.events)
    assert res.end["data"]["turn"] == 2


def test_fold_consumed_work_ignores_unclaimed_turns():
    session = Session.create("no-claim")
    stepped_turn(session, 1, {"kind": "completed"})
    session.append("turn/start", {"turn": 2})
    session.append("turn/end", {"turn": 2, "reason": {"kind": "aborted", "reason": {"kind": "parent"}}})
    session.append("turn/start", {"turn": 3})
    session.append("turn/end", {"turn": 3, "reason": {"kind": "error", "error": {"message": "x", "code": "UNKNOWN"}}})
    session.append("turn/start", {"turn": 4})
    session.append("turn/end", {"turn": 4, "reason": {"kind": "blocked"}})

    res = fold_consumed_work(session.events)
    assert res.end["data"]["turn"] == 1


def test_fold_consumed_work_rejected_claim_discard():
    session = Session.create("rejected-claim")
    stepped_turn(session, 1, {"kind": "completed"})
    session.append("turn/start", {"turn": 2})
    claim(session)
    session.append("turn/end", {"turn": 2, "reason": {"kind": "blocked"}})

    res = fold_consumed_work(session.events)
    assert res.end["data"]["turn"] == 2


def test_fold_consumed_work_stops_at_previous_turn_boundary():
    session = Session.create("turn-boundary")
    stepped_turn(session, 1, {"kind": "completed"})
    # Turn 2 opened, claimed nothing, and has not yet ended
    session.append("turn/start", {"turn": 2})

    res = fold_consumed_work(session.events)
    assert res.end["data"]["turn"] == 1


def test_fold_consumed_work_reports_canceled_input():
    session = Session.create("canceled-input")
    accept(session, "queued")
    cancel_pending(session)

    res = fold_consumed_work(session.events)
    assert res.dropped_unrun is True
    assert res.end is None


def test_fold_consumed_work_canceled_alongside_completed_turn():
    session = Session.create("canceled-with-work")
    stepped_turn(session, 1, {"kind": "completed"})
    accept(session, "queued")
    cancel_pending(session)

    res = fold_consumed_work(session.events)
    assert res.end["data"]["turn"] == 1
    assert res.dropped_unrun is True


def test_fold_consumed_work_ignores_clean_claims():
    session = Session.create("clean-claims")
    accept(session, "queued")
    claim(session)

    res = fold_consumed_work(session.events)
    assert res.dropped_unrun is False
