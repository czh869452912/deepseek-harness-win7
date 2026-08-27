import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.events import AggregateError, EventBus
from dsh.cordis.context import Context


def test_emit_propagates_listener_exceptions_synchronously():
    bus = EventBus()

    def fail():
        raise RuntimeError("emit failed")

    bus.on("event", fail)

    with pytest.raises(RuntimeError, match="emit failed"):
        bus.emit("event")


@pytest.mark.asyncio
async def test_parallel_fans_out_before_waiting_and_aggregates_failures():
    bus = EventBus()
    both_started = asyncio.Event()
    started = []

    async def listener(name, fail=False):
        started.append(name)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.5)
        if fail:
            raise ValueError(name)
        return name

    bus.on("event", lambda: listener("first", fail=True))
    bus.on("event", lambda: listener("second"))

    with pytest.raises(AggregateError) as error:
        await bus.parallel("event")

    assert started == ["first", "second"]
    assert [str(item) for item in error.value.errors] == ["first"]


@pytest.mark.asyncio
async def test_parallel_success_resolves_to_none():
    bus = EventBus()
    bus.on("event", lambda: "ignored")

    assert await bus.parallel("event") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("include_regular_error", [False, True])
async def test_parallel_propagates_listener_cancellation(include_regular_error):
    bus = EventBus()

    async def cancelled():
        raise asyncio.CancelledError()

    bus.on("event", cancelled)
    if include_regular_error:
        bus.on("event", lambda: (_ for _ in ()).throw(ValueError("failed")))

    with pytest.raises(asyncio.CancelledError):
        await bus.parallel("event")


@pytest.mark.asyncio
async def test_serial_awaits_in_order_and_stops_on_first_bail_value():
    bus = EventBus()
    calls = []

    async def first():
        calls.append("first")
        await asyncio.sleep(0)
        return False

    async def second():
        calls.append("second")
        return 0

    bus.on("event", first)
    bus.on("event", second)
    bus.on("event", lambda: calls.append("unreachable"))

    assert await bus.serial("event") == 0
    assert calls == ["first", "second"]


def test_waterfall_passes_original_arguments_and_composes_around_inner_next():
    bus = EventBus()
    calls = []

    def outer(config, no_save, next_fn):
        calls.append(("outer:before", config, no_save))
        result = next_fn()
        calls.append(("outer:after", result))
        return "wrapped:" + result

    def inner_listener(config, no_save, next_fn):
        calls.append(("listener", config, no_save))
        return next_fn()

    def builtin(config, no_save):
        calls.append(("builtin", config, no_save))
        return "done"

    bus.on("event", outer)
    bus.on("event", inner_listener)

    assert bus.waterfall_sync("event", {"x": 1}, False, builtin) == "wrapped:done"
    assert calls == [
        ("outer:before", {"x": 1}, False),
        ("listener", {"x": 1}, False),
        ("builtin", {"x": 1}, False),
        ("outer:after", "done"),
    ]


def test_waterfall_listener_can_veto_inner_next():
    bus = EventBus()
    calls = []

    bus.on("event", lambda value, next_fn: calls.append("veto") or "stopped")

    result = bus.waterfall_sync(
        "event", "value", lambda value: calls.append("builtin") or value
    )

    assert result == "stopped"
    assert calls == ["veto"]


def test_waterfall_treats_non_callable_last_argument_as_inner():
    bus = EventBus()

    with pytest.raises(TypeError):
        bus.waterfall_sync("event", "not-a-callback")


def test_waterfall_distinguishes_registered_listener_from_same_inner_callable():
    bus = EventBus()
    arities = []

    def shared(*args):
        arities.append(len(args))
        if len(args) == 2:
            return args[-1]()
        return "done"

    bus.on("event", shared)

    assert bus.waterfall_sync("event", "value", shared) == "done"
    assert arities == [2, 1]


def test_prepend_once_and_bail_match_upstream_ordering():
    bus = EventBus()
    calls = []

    bus.on("event", lambda: calls.append("normal") or None)
    bus.once("event", lambda: calls.append("once") or False, prepend=True)
    bus.on("event", lambda: calls.append("bail") or "result")

    assert bus.bail_sync("event") == "result"
    assert calls == ["once", "normal", "bail"]

    calls.clear()
    assert bus.bail_sync("event") == "result"
    assert calls == ["normal", "bail"]


def test_dispatch_filters_listener_owner_context_and_global_bypasses_filter():
    bus = EventBus()
    allowed = SimpleNamespace(name="allowed")
    denied = SimpleNamespace(name="denied")
    caller = SimpleNamespace(filter=lambda owner: owner is allowed)
    calls = []

    bus.on("event", lambda: calls.append("allowed"), ctx=allowed)
    bus.on("event", lambda: calls.append("denied"), ctx=denied)
    bus.on(
        "event",
        lambda: calls.append("global"),
        global_listener=True,
        ctx=denied,
    )

    bus.emit("event", caller_ctx=caller)

    assert calls == ["allowed", "global"]


def test_plain_context_dispatch_is_visible_to_sibling_listener():
    root = Context()
    first = root.extend()
    second = root.extend()
    calls = []

    first.on("event", lambda: calls.append("first"))
    second.emit("event")

    assert calls == ["first"]


def test_internal_update_hooks_are_local_to_the_target_fiber():
    bus = EventBus()
    fiber_one = SimpleNamespace(_hooks={})
    fiber_two = SimpleNamespace(_hooks={})
    owner_one = SimpleNamespace(fiber=fiber_one)
    owner_two = SimpleNamespace(fiber=fiber_two)
    calls = []

    bus.on(
        "internal/update",
        lambda config, no_save, next_fn: calls.append("one") or next_fn(),
        ctx=owner_one,
    )
    bus.on(
        "internal/update",
        lambda config, no_save, next_fn: calls.append("two") or next_fn(),
        ctx=owner_two,
    )

    result = bus.waterfall_sync(
        "internal/update",
        {"value": 1},
        False,
        lambda config, no_save: calls.append("builtin") or "updated",
        caller_ctx=owner_one,
    )

    assert result == "updated"
    assert calls == ["one", "builtin"]
    assert len(fiber_one._hooks["internal/update"]) == 1
    assert len(fiber_two._hooks["internal/update"]) == 1


def test_internal_update_bridge_keeps_global_prepend_priority():
    bus = EventBus()
    fiber = SimpleNamespace(_hooks={})
    owner = SimpleNamespace(fiber=fiber)
    calls = []

    bus.on(
        "internal/update",
        lambda config, no_save, next_fn: calls.append("local") or next_fn(),
        ctx=owner,
    )
    bus.on(
        "internal/update",
        lambda config, no_save, next_fn: calls.append("global-normal")
        or next_fn(),
        global_listener=True,
    )
    bus.on(
        "internal/update",
        lambda config, no_save, next_fn: calls.append("global-prepend")
        or next_fn(),
        prepend=True,
        global_listener=True,
    )

    bus.waterfall_sync(
        "internal/update",
        {},
        False,
        lambda config, no_save: calls.append("builtin"),
        caller_ctx=owner,
    )

    assert calls == ["global-prepend", "local", "global-normal", "builtin"]


@pytest.mark.parametrize(
    "event_name",
    ["internal/config", "internal/get", "internal/set", "internal/update"],
)
def test_fiber_local_internal_bridges_keep_global_hooks(event_name):
    bus = EventBus()
    first = SimpleNamespace(fiber=SimpleNamespace(_hooks={}))
    second = SimpleNamespace(fiber=SimpleNamespace(_hooks={}))
    calls = []

    bus.on(
        event_name,
        lambda value, next_fn: calls.append("first") or next_fn(),
        ctx=first,
    )
    bus.on(
        event_name,
        lambda value, next_fn: calls.append("second") or next_fn(),
        ctx=second,
    )
    bus.on(
        event_name,
        lambda value, next_fn: calls.append("global") or next_fn(),
        global_listener=True,
    )

    result = bus.waterfall_sync(
        event_name,
        1,
        lambda value: calls.append("builtin") or value + 1,
        caller_ctx=first,
    )

    assert result == 2
    assert calls == ["first", "global", "builtin"]
