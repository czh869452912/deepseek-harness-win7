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
    ctx.dispose()


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
