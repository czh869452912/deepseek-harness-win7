import pytest
from dsh.cordis.context import Context
from dsh.session.title import normalize_session_title, fallback_session_title, SessionTitleService
from dsh.session.stats import SessionStatsPlugin
from dsh.session.projections import SessionProjectionsPlugin
from dsh.core.session import SessionStore


def test_title_normalization():
    raw = "\x1b[31mHello\x1b[0m \n World!\u200b"
    norm = normalize_session_title(raw)
    assert norm == "Hello World!"


def test_fallback_title():
    events = [
        {"type": "user/message", "data": {"content": "Fix the bug in main.py"}}
    ]
    title = fallback_session_title(events)
    assert title == "Fix the bug in main.py"


def test_session_stats_projection():
    ctx = Context()
    SessionProjectionsPlugin().apply(ctx)
    SessionStatsPlugin().apply(ctx)

    store = SessionStore(ctx)
    session = store.create("test-stats-session")

    session.append("step/start", {"turn": 1, "step": 1})
    session.append("assistant/message", {"message": {"content": "ok"}, "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    session.append("step/end", {"turn": 1, "step": 1})

    projections = ctx.get("sessionProjections")
    snap = projections.snapshot(session)
    stats = snap["values"].get("sessionStats", {})

    assert stats["steps"] == 1
    assert stats["turns"] == 1
    assert stats["promptTokens"] == 10
    assert stats["completionTokens"] == 5
