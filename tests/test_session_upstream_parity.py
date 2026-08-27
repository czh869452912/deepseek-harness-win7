import pytest

from dsh.cordis.context import Context
from dsh.core.session import Session, SessionForkError, SessionStore


def test_prepare_enter_announce_and_exact_disposal():
    ctx = Context()
    store = SessionStore(ctx)
    created = []
    disposed = []
    ctx.on("session/created", lambda session: created.append(session.id))
    ctx.on("session/disposed", lambda session: disposed.append(session.id))

    prepared = store.prepare("prepared")
    assert store.get("prepared") is None
    detach = store.enter(prepared)
    assert store.get("prepared") is prepared
    assert created == []
    store.announce(prepared)
    assert created == ["prepared"]
    detach()
    detach()
    assert store.get("prepared") is None
    assert disposed == ["prepared"]


def test_seed_marker_is_detached_until_publication():
    ctx = Context()
    store = SessionStore(ctx)
    observed = []
    ctx.on("session/event", lambda session, event: observed.append(event["type"]))
    session = store.create("seeded", seed=[{"type": "turn/end", "seq": 0, "time": 0, "data": {}}])
    assert observed == []
    session.append("turn/end", {})
    assert observed == ["turn/end"]


def test_fork_copies_stable_prefix_and_reports_typed_errors():
    store = SessionStore(Context())
    source = store.create("parent")
    source.append("turn/start", {"turn": 1})
    source.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
    child = store.fork(source, 1, "child")
    assert child.header.parent_session == "parent"
    assert child.header.seed_length == 2
    assert [event["type"] for event in child.events[:2]] == ["turn/start", "turn/end"]

    with pytest.raises(SessionForkError) as missing:
        store.fork("unknown")
    assert missing.value.code == "SESSION_NOT_FOUND"

    source.append("turn/start", {"turn": 2})
    with pytest.raises(SessionForkError) as open_turn:
        store.fork(source, source.events[-1]["seq"])
    assert open_turn.value.code == "OPEN_TURN"


def test_empty_fork_and_deep_snapshot_boundary():
    store = SessionStore(Context())
    source = store.create("empty-parent")
    child = store.fork(source, child_session_id="empty-child")
    assert child.header.seed_length == 0
    assert child.events[-1]["type"] == "session/end-seed"

    source.append("turn/end", {"nested": {"value": 1}})
    child2 = store.fork(source, child_session_id="copy")
    child2.events[0]["data"]["nested"]["value"] = 99
    assert source.events[0]["data"]["nested"]["value"] == 1


@pytest.mark.parametrize("kwargs", [
    {"version": 9}, {"created_at": -1}, {"parent_session": 1},
    {"seed_length": -1}, {"delegation_depth": -1}, {"origin": "user"},
    {"agent_preset": 1},
])
def test_session_header_rejects_invalid_metadata(kwargs):
    with pytest.raises(ValueError):
        from dsh.core.session import SessionHeader
        SessionHeader("bad", **kwargs)


@pytest.mark.asyncio
async def test_flush_reports_listener_participation():
    ctx = Context()
    store = SessionStore(ctx)
    session = store.create("flush")
    assert await store.flush(session) is False
    ctx.on("session/flush", lambda _session: None)
    assert await store.flush(session) is True
