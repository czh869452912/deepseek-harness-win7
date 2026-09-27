"""Source-backed registry regressions; paired observations live in scripts/oracles."""
import gc
import weakref

import pytest

from dsh.cordis.context import Context
from dsh.core.session import Session
from dsh.session.projections import SessionProjectionRegistry


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer")
    return value


def count(key="count", wire=True, **overrides):
    definition = dict(key=key, stateSchema=integer, init=lambda header: 0,
                      apply=lambda state, event: state + 1, stateVersion=1)
    if wire:
        definition["wire"] = wire if isinstance(wire, dict) else dict(viewSchema=integer, view=lambda state: state)
    definition.update(overrides)
    return definition


def test_late_drive_replays_prefix_and_never_double_applies_observed_events():
    registry = SessionProjectionRegistry()
    session = Session("late")
    session.append("test/mark", {})
    registry.register(count())
    changes = []
    registry.onChanged(lambda s, k, v, seq: changes.append((v, seq)))
    event = session.append("test/mark", {})
    registry.on_session_event(session, event)
    registry.on_session_event(session, event)
    assert registry.snapshot(session) == {"asOfSeq": 1, "values": {"count": 2}}
    assert changes == [(2, 1)]
    event = session.append("test/mark", {})
    registry.snapshot(session)  # A read can precede event delivery.
    registry.on_session_event(session, event)
    assert changes == [(2, 1)]


def test_exact_session_identity_and_weak_ownership():
    registry = SessionProjectionRegistry()
    registry.register(count())
    first, second = Session("same"), Session("same")
    first.append("test/mark", {})
    assert registry.snapshot(first)["values"] == {"count": 1}
    assert registry.snapshot(second)["values"] == {"count": 0}
    ref = weakref.ref(first)
    del first
    gc.collect()
    assert ref() is None


@pytest.mark.asyncio
async def test_shared_registration_owned_by_each_calling_fiber():
    ctx = Context()
    registry = SessionProjectionRegistry(ctx)
    disposers = []

    def mount(child):
        disposers.append(child.sessionProjections.register(count()))
    one = ctx.plugin(mount)
    two = ctx.plugin(lambda child: mount(child))
    await one
    await two
    await one.dispose()
    assert registry.has("count")
    disposers[0]()  # Already disposed; cannot decrement the other owner.
    assert registry.has("count")
    await two.dispose()
    assert not registry.has("count")
    await ctx.fiber.dispose()


@pytest.mark.parametrize("version", [-1, 0.5, True, 9007199254740992])
def test_invalid_versions_reject_before_registration(version):
    registry = SessionProjectionRegistry()
    with pytest.raises(ValueError):
        registry.register(count(stateVersion=version))
    assert not registry.has("count")


def test_version_conflict_and_first_definition_ownership():
    registry = SessionProjectionRegistry()
    remove = registry.register(count())
    other = registry.register(count(init=lambda header: 100))
    with pytest.raises(ValueError):
        registry.register(count(stateVersion=2))
    assert registry.stateOf(Session("s"), "count") == 0
    remove()
    remove()
    assert registry.has("count")
    other()
    assert not registry.has("count")


def test_selective_snapshot_materializes_host_units_without_viewing_them():
    registry, session = SessionProjectionRegistry(), Session("s")
    session.append("test/mark", {})
    assert registry.snapshot(session) == {"asOfSeq": 0, "values": {}}
    seen = []
    registry.register(count("host", wire=False, init=lambda header: seen.append(header.id) or 0))
    registry.register(count("wire"))
    assert registry.cachedSnapshot(session) is None
    assert registry.snapshot(session, []) == {"asOfSeq": 0, "values": {}}
    assert seen == ["s"]
    assert registry.stateOf(session, "host") == 1
    assert registry.cachedSnapshot(session) == {"asOfSeq": 0, "values": {"wire": 1}}
    session.append("test/mark", {})
    assert registry.cachedSnapshot(session)["asOfSeq"] == 0


def test_wire_validation_and_listener_errors_propagate_after_watermark_commit():
    registry, session = SessionProjectionRegistry(), Session("s")
    registry.register(count(wire=dict(viewSchema=integer, view=lambda state: -1)))
    event = session.append("test/mark", {})
    registry.on_session_event(session, event)  # No listeners, no view work.
    with pytest.raises(ValueError):
        registry.snapshot(session)
    registry = SessionProjectionRegistry()
    registry.register(count())
    def fail(*args):
        raise RuntimeError("listener")
    registry.onChanged(fail)
    with pytest.raises(RuntimeError, match="listener"):
        registry.on_session_event(session, event)
    registry.on_session_event(session, event)
    assert registry.stateOf(session, "count") == 1


def test_equal_primitive_states_do_not_emit_changes():
    registry, session = SessionProjectionRegistry(), Session("s")
    registry.register(count(init=lambda header: 1000, apply=lambda state, event: int("1000")))
    changes = []
    registry.onChanged(lambda *args: changes.append(args))
    registry.on_session_event(session, session.append("test/mark", {}))
    assert changes == []


def test_checkpoint_detaches_mutable_state_and_includes_host_only_units():
    registry, session = SessionProjectionRegistry(), Session("s")
    registry.register(count("host", wire=False))
    registry.register(count("list", wire=False, init=lambda header: [],
                            apply=lambda state, event: state + [event["seq"]]))
    session.append("test/mark", {})
    rows = registry.checkpoint(session)
    rows["list"]["val"].append(99)
    assert registry.stateOf(session, "list") == [0]
    assert rows["host"] == dict(ver=1, seq=0, val=1)
    assert registry.snapshot(session)["values"] == {}


def test_restore_floor_anchors_below_lowest_matching_row():
    registry = SessionProjectionRegistry()
    assert registry.restoreFloor({}) is None
    registry.register(count())
    registry.register(count("host", wire=False))
    rows = dict(count=dict(ver=1, seq=5, val=6), host=dict(ver=1, seq=3, val=4))
    assert registry.restoreFloor(rows) == 3
    rows["host"]["ver"] = 2
    assert registry.restoreFloor(rows) == 0
    assert registry.restoreFloor({}) == 0


def test_restore_suffix_empty_tail_and_truncation_refold():
    registry, session = SessionProjectionRegistry(), Session("s")
    registry.register(count())
    for _ in range(5):
        session.append("test/mark", {})
    rows = dict(count=dict(ver=1, seq=2, val=3))
    restored = registry.restore(rows, session.events[2:], 2, session.header)
    assert restored == dict(snapshot=dict(asOfSeq=4, values=dict(count=5)),
                            checkpoint=dict(count=dict(ver=1, seq=4, val=5)))
    assert registry.restore(restored["checkpoint"], [], 5, session.header) == restored
    with pytest.raises(ValueError, match="re-read from seq 0"):
        registry.restore(restored["checkpoint"], [], 4, session.header)
    rebuilt = registry.restore(restored["checkpoint"], session.events[:2], 0, session.header)
    assert rebuilt["snapshot"] == dict(asOfSeq=1, values=dict(count=2))
    with pytest.raises(ValueError, match="missing seq 0"):
        registry.restore({}, session.events[1:], 0, session.header)


def test_state_schema_rejects_restore_but_skips_bad_checkpoint_hint():
    registry, session = SessionProjectionRegistry(), Session("s")
    registry.register(count())
    rows = dict(count=dict(ver=1, seq=-1, val="bad"))
    assert registry.viewCheckpoint(rows) == {}
    with pytest.raises(ValueError, match="nonnegative"):
        registry.restore(rows, [], 0, session.header)
    rows["count"].update(val=0)
    assert registry.viewCheckpoint(rows) == dict(count=0)
    assert registry.viewCheckpoint(rows, []) == {}


def test_hydrate_reuses_exact_cut_and_advances_suffix_once_without_rewinding():
    registry, session = SessionProjectionRegistry(), Session("s")
    calls = []
    registry.register(count(apply=lambda state, event: calls.append(event["seq"]) or state + 1))
    for _ in range(3):
        session.append("test/mark", {})
    prefix = session.events[:2]
    assert registry.hydrate(session, {}, prefix, 0)["values"] == dict(count=2)
    assert registry.hydrate(session, {}, prefix, 0)["values"] == dict(count=2)
    assert calls == [0, 1]
    assert registry.snapshot(session)["values"] == dict(count=3)
    registry.on_session_event(session, session.events[-1])
    assert calls == [0, 1, 2]
    registry.hydrate(session, {}, prefix, 0)
    assert registry.stateOf(session, "count") == 3
