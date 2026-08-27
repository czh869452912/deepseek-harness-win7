from dsh.cordis.context import Context
from dsh.core.runtime_context import CLEARED, RuntimeContextProjection, SOURCE
from dsh.core.session import SessionPlugin


def _session():
    ctx = Context()
    SessionPlugin().apply(ctx)
    return ctx, ctx.get("sessions").create("runtime-context-parity")


def test_empty_projection_is_uninitialized_until_context_exists():
    ctx, session = _session()
    projection = RuntimeContextProjection(ctx, session)
    assert projection.retained is None
    assert projection.project("", []) is None


def test_replacement_of_retained_snapshot_emits_next_snapshot():
    ctx, session = _session()
    first = session.append(
        "user/message",
        {"content": [{"type": "text", "text": "old"}], "source": {"kind": "plugin", "plugin": SOURCE}},
        surface_op="append",
    )
    projection = RuntimeContextProjection(ctx, session)
    session.append(
        "user/message",
        {"content": [{"type": "text", "text": "unrelated"}], "source": {"kind": "plugin", "plugin": "other"}},
        surface_op={"op": "replace", "start": 0, "end": 0},
        source_event_seqs=[first["seq"]],
    )
    assert projection.retained is None
    candidate = projection.project("new", [{"name": "policy", "text": "new"}])
    assert candidate["content"][0]["text"] == "new"


def test_empty_active_context_uses_cleared_marker_after_eviction():
    ctx, session = _session()
    first = session.append(
        "user/message",
        {"content": "old", "source": {"kind": "plugin", "plugin": SOURCE}},
        surface_op="append",
    )
    projection = RuntimeContextProjection(ctx, session)
    session.append(
        "user/message",
        {"content": "other", "source": {"kind": "plugin", "plugin": "other"}},
        surface_op={"op": "replace", "start": 0, "end": 0},
        source_event_seqs=[first["seq"]],
    )
    candidate = projection.project("", [])
    assert candidate["content"][0]["text"] == CLEARED
