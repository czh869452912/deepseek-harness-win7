"""
1:1 parity unit test suite for dsh/cordis/fiber.py matching reference/vendor/cordis/src/fiber.ts.
Covers:
- T1: Parent unload cascades dispose to child fibers (D1)
- T2: Direct fiber.dispose() deregisters from registry and runtime.fibers (D2)
- T3: internal/plugin disposed event emitted before unload with listener error isolation (D3)
- T4: inject intercept config populated on ctx._intercept_map (D4)
- T5: name property inherits from nearest named ancestor (D5)
- T6: FAILED fiber still allows effect registration (D6)
- T16: Disposed fiber with error reports DISPOSED state (D16)
- T17: CordisError default message text (D17)
- T18: Root fiber dispose restarts instead of destroying (D18)
- T20: Fiber.effect accepts a synchronous iterable effect result and disposes
  the collected disposers in reverse registration order (fiber.ts `_execute`
  `Symbol.iterator in effect` branch)
- T21: An invalid produced value fails the effect with TypeError("Invalid
  effect") and rolls the already-collected disposers back in reverse order
- T22: Synchronous iterables are accepted beyond generators (tuple/protocol
  object), matching `Symbol.iterator in effect`
- T23: A synchronous iterable that throws mid-iteration rolls back and
  re-propagates the iteration error
- T24: A primitive effect result (str/bytes/int) is never iterated and is
  rejected as an invalid effect (`!isObject(effect)`)
- T25: An `apply` body returning a custom synchronous iterable is drained by
  the fiber itself (`_execute` `Symbol.iterator in effect`), not only a plain
  generator/list/tuple
- T26: A non-disposer item in a body-returned iterable fails the fiber with
  TypeError("Invalid effect")
- T27: `Fiber.effect` also accepts an arbitrary async iterable result
  (`_execute` `Symbol.asyncIterator in effect`), draining it on a task through
  the effect collect with the load-epoch re-check
- T28: A failing async iterable rolls the collected disposers back and rejects
  the awaited public disposer (`wrapper.then` over the rejected setup task)
- T29: A non-disposer item yielded by an async iterable fails the effect with
  TypeError("Invalid effect") after rolling the collected disposers back
- T30: The terminal value of a body-returned iterator is collected like every
  other produced value (`safeCollect` runs before the `done` check)
"""

import asyncio
import pytest
from typing import Any

from dsh.cordis.context import Context
from dsh.cordis.fiber import CordisError, Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


@pytest.mark.asyncio
async def test_t1_parent_unload_disposes_child_fibers():
    """T1 (D1): Parent unload cascades dispose to child fibers."""
    ctx = Context()
    child_disposed = []

    class ChildPlugin(Plugin):
        name = "child_plugin"

        def apply(self, c: Context) -> None:
            c.effect(lambda: (lambda: child_disposed.append(True)))

    class ParentPlugin(Plugin):
        name = "parent_plugin"

        def apply(self, c: Context) -> None:
            c.plugin(ChildPlugin)

    parent_fiber = ctx.plugin(ParentPlugin)
    assert parent_fiber.state == FiberState.ACTIVE
    assert ctx.registry.has(ChildPlugin)

    await parent_fiber.dispose()

    assert parent_fiber.state == FiberState.DISPOSED
    assert len(child_disposed) == 1
    assert not ctx.registry.has(ChildPlugin)


@pytest.mark.asyncio
async def test_t2_direct_fiber_dispose_deregisters_from_registry():
    """T2 (D2): Direct fiber.dispose() deregisters from registry."""
    ctx = Context()

    class SimplePlugin(Plugin):
        name = "simple_plugin"

    fiber = ctx.plugin(SimplePlugin)
    assert ctx.registry.has(SimplePlugin)

    await fiber.dispose()

    assert fiber.state == FiberState.DISPOSED
    assert not ctx.registry.has(SimplePlugin)
    assert fiber not in ctx.registry.list_fibers()


@pytest.mark.asyncio
async def test_t3_internal_plugin_disposed_event_before_unload_and_error_isolated():
    """T3 (D3): internal/plugin disposed event is emitted before unload with listener error isolation."""
    ctx = Context()
    event_order = []

    class TrackedPlugin(Plugin):
        name = "tracked_plugin"

        def apply(self, c: Context) -> None:
            c.effect(lambda: (lambda: event_order.append("effect_unloaded")))

    def on_plugin_1(fiber: Fiber):
        if fiber.uid is None:
            event_order.append("event_uid_none")

    def on_plugin_failing(fiber: Fiber):
        if fiber.uid is None:
            raise RuntimeError("Listener error must be isolated")

    ctx.on("internal/plugin", on_plugin_1)
    ctx.on("internal/plugin", on_plugin_failing)

    fiber = ctx.plugin(TrackedPlugin)
    await fiber.dispose()

    assert "event_uid_none" in event_order
    assert "effect_unloaded" in event_order
    # Event emitted before unload
    assert event_order.index("event_uid_none") < event_order.index("effect_unloaded")


@pytest.mark.asyncio
async def test_t4_inject_intercept_config_reaches_intercept_map():
    """T4 (D4): inject intercept config is written to ctx._intercept_map."""
    ctx = Context()
    ctx.provide("my_service", object())
    captured_intercept = {}

    class InterceptConsumer(Plugin):
        name = "intercept_consumer"
        inject = {"my_service": {"custom_intercept_key": "custom_val"}}

        def apply(self, c: Context) -> None:
            captured_intercept.update(getattr(c, "_intercept_map", {}))

    fiber = ctx.plugin(InterceptConsumer)
    assert fiber.state == FiberState.ACTIVE
    assert "my_service" in captured_intercept
    assert captured_intercept["my_service"] == {"custom_intercept_key": "custom_val"}


@pytest.mark.asyncio
async def test_t5_name_inherits_nearest_named_ancestor():
    """T5 (D5): Anonymous child fiber inherits name of nearest named ancestor."""
    ctx = Context()
    child_fiber_ref = []

    class NamedParent(Plugin):
        name = "grand_parent_runtime"

        def apply(self, c: Context) -> None:
            f = c.plugin(lambda child_ctx: None)
            child_fiber_ref.append(f)

    parent_fiber = ctx.plugin(NamedParent)
    assert len(child_fiber_ref) == 1
    child_fiber = child_fiber_ref[0]
    assert child_fiber.name == "grand_parent_runtime"


@pytest.mark.asyncio
async def test_t6_failed_fiber_still_allows_effect_registration():
    """T6 (D6): FAILED fiber (uid not None) still allows effect registration."""
    ctx = Context()

    class FailingPlugin(Plugin):
        name = "failing_plugin"

        def apply(self, c: Context) -> None:
            raise ValueError("Intentional startup failure")

    fiber = ctx.plugin(FailingPlugin)
    assert fiber.state == FiberState.FAILED
    assert fiber.uid is not None

    # Should not raise CordisError("INACTIVE_EFFECT")
    cleaned = []
    disposer = fiber.ctx.effect(lambda: (lambda: cleaned.append(True)))
    assert callable(disposer)

    await fiber.dispose()
    assert len(cleaned) == 1


@pytest.mark.asyncio
async def test_t16_disposed_fiber_with_error_reports_disposed():
    """T16 (D16): Disposed fiber that previously failed reports DISPOSED, not FAILED."""
    ctx = Context()

    class FailingPlugin(Plugin):
        name = "failing_plugin"

        def apply(self, c: Context) -> None:
            raise ValueError("Fatal crash")

    fiber = ctx.plugin(FailingPlugin)
    assert fiber.state == FiberState.FAILED

    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED


def test_t17_cordis_error_default_message_text():
    """T17 (D17): CordisError default message text matches CODE_MESSAGES."""
    err = CordisError("INACTIVE_EFFECT")
    assert str(err) == "cannot create effect on inactive context"
    assert err.code == "INACTIVE_EFFECT"


@pytest.mark.asyncio
async def test_t18_root_fiber_dispose_restarts_instead_of_destroying():
    """T18 (D18): Root fiber dispose restarts rather than transitioning to DISPOSED."""
    ctx = Context()
    root_fiber = ctx.fiber
    assert root_fiber.uid == 0
    assert root_fiber.state == FiberState.ACTIVE

    await root_fiber.dispose()
    assert root_fiber.uid == 0
    assert root_fiber.state in (FiberState.ACTIVE, FiberState.LOADING)


def test_t19_apply_raising_typeerror_not_retried():
    """T19: A plugin whose apply raises TypeError executes only once and does not get retried."""
    ctx = Context()
    execution_count = [0]

    class BadApplyPlugin(Plugin):
        name = "bad_apply_plugin"

        def apply(self, c: Context, config: Any = None) -> None:
            execution_count[0] += 1
            raise TypeError("internal type error")

    fiber = ctx.plugin(BadApplyPlugin)
    assert fiber.state == FiberState.FAILED
    assert execution_count[0] == 1


@pytest.mark.asyncio
async def test_t20_effect_accepts_sync_iterable_and_disposes_in_reverse_order():
    """T20: `Fiber.effect` accepts an iterable of disposers, disposed in reverse.

    Reference: fiber.ts `_execute` `Symbol.iterator in effect` branch pushes each
    produced item through the effect `collect`, and `effect` `dispose` runs the
    collected disposers with `disposables.splice(0).reverse()`.
    """
    ctx = Context()
    log = []

    disposer = ctx.effect(
        lambda: [
            lambda: log.append("first"),
            lambda: log.append("second"),
            lambda: log.append("third"),
        ],
        "t20-iterable",
    )

    # one labeled effect owning three bare disposers (no nested effect metas)
    assert ctx.fiber.get_effects() == [{"label": "t20-iterable", "children": []}]
    assert log == []

    disposer()
    assert log == ["third", "second", "first"]
    assert ctx.fiber.get_effects() == []

    # the public disposer is single-shot: a second call is a no-op
    disposer()
    assert log == ["third", "second", "first"]


@pytest.mark.asyncio
async def test_t21_effect_sync_iterable_invalid_item_rolls_back_collected_disposers():
    """T21: an invalid produced value rolls back the disposers already collected.

    Reference: fiber.ts `_execute` `safeCollect` throws
    `TypeError('Invalid effect')` for a value that is neither a disposer nor
    null; the `effect` failure path then finalizes disposal of the collected
    disposers in reverse order before rethrowing.
    """
    ctx = Context()
    log = []

    def body():
        return [
            lambda: log.append("first"),
            lambda: log.append("second"),
            "not-a-disposer",
        ]

    with pytest.raises(TypeError, match="Invalid effect"):
        ctx.effect(body, "t21-invalid")

    assert log == ["second", "first"]
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_t22_effect_accepts_sync_iterables_beyond_generators():
    """T22: tuple and custom-iterable effect results are collected like generators.

    Reference: fiber.ts tests `Symbol.iterator in effect`, not a generator brand,
    so every object exposing the synchronous iteration protocol is accepted.
    """
    ctx = Context()
    log = []

    def d1():
        log.append("t1")

    def d2():
        log.append("t2")

    tuple_disposer = ctx.effect(lambda: (d1, d2), "t22-tuple")
    assert ctx.fiber.get_effects() == [{"label": "t22-tuple", "children": []}]
    tuple_disposer()
    assert log == ["t2", "t1"]

    class DisposerIterable:
        def __init__(self, items):
            self._items = items

        def __iter__(self):
            return iter(self._items)

    protocol_disposer = ctx.effect(lambda: DisposerIterable([d1, d2]), "t22-protocol")
    assert ctx.fiber.get_effects() == [{"label": "t22-protocol", "children": []}]
    protocol_disposer()
    assert log == ["t2", "t1", "t2", "t1"]


@pytest.mark.asyncio
async def test_t23_effect_iterable_iteration_error_rolls_back_and_propagates():
    """T23: an iteration error rolls back collected disposers and re-propagates.

    Reference: the `Symbol.iterator in effect` branch loops inside
    `composeError`, so a throw from `next()` rejects `effect()` with the original
    error after the effect has been finalized.
    """
    ctx = Context()
    log = []

    def body():
        yield lambda: log.append("collected")
        raise RuntimeError("iteration boom")

    with pytest.raises(RuntimeError, match="iteration boom"):
        ctx.effect(body, "t23-throw")

    assert log == ["collected"]
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_t24_effect_primitive_result_is_not_iterated():
    """T24: a primitive effect result is an invalid effect, never an iterable.

    Reference: fiber.ts `_execute` rejects `!isObject(effect)` before the
    iterator branches, so a string result is a `TypeError('Invalid effect')`
    rather than a stream of single-character disposers.
    """
    ctx = Context()

    with pytest.raises(TypeError, match="Invalid effect"):
        ctx.effect(lambda: "disposers", "t24-str")

    with pytest.raises(TypeError, match="Invalid effect"):
        ctx.effect(lambda: b"disposers", "t24-bytes")

    with pytest.raises(TypeError, match="Invalid effect"):
        ctx.effect(lambda: 7, "t24-int")

    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_t25_apply_returning_custom_sync_iterable_collects_disposers_on_fiber():
    """T25: the plugin body accepts any synchronous iterable result.

    Reference: fiber.ts `_execute` dispatches on `Symbol.iterator in effect`, so
    the disposers yielded by an `apply` body are collected on the fiber itself
    regardless of the concrete iterable type; they carry no effect metadata.
    """
    ctx = Context()
    log = []

    class DisposerIterable:
        def __init__(self, items):
            self._items = items

        def __iter__(self):
            return iter(self._items)

    class IterablePlugin(Plugin):
        name = "iterable_plugin"

        def apply(self, c: Context):
            return DisposerIterable([
                lambda: log.append("first"),
                lambda: log.append("second"),
            ])

    fiber = ctx.plugin(IterablePlugin)
    assert fiber.state == FiberState.ACTIVE
    assert fiber.get_effects() == []

    await fiber.dispose()
    assert log == ["second", "first"]


@pytest.mark.asyncio
async def test_t26_apply_returning_iterable_with_non_disposer_fails_loud():
    """T26: a non-disposer item in the returned iterable fails the fiber.

    Reference: `_execute` `safeCollect` rejects a produced value that is neither
    a disposer nor null, so the fiber enters FAILED with `TypeError`.
    """
    ctx = Context()

    class BadIterablePlugin(Plugin):
        name = "bad_iterable_plugin"

        def apply(self, c: Context):
            return [lambda: None, 42]

    fiber = ctx.plugin(BadIterablePlugin)
    assert fiber.state == FiberState.FAILED
    assert isinstance(fiber.error, TypeError)
    assert "Invalid effect" in str(fiber.error)


@pytest.mark.asyncio
async def test_t27_effect_accepts_custom_async_iterable():
    """T27: `effect` accepts any async iterable, not only async generators.

    Reference: fiber.ts `_execute` dispatches on `Symbol.asyncIterator in effect`
    and drains the iterator on a task, re-checking the load epoch and collecting
    each produced disposer through the effect `collect`.
    """
    ctx = Context()
    log = []

    class AsyncDisposerIterable:
        def __init__(self, items):
            self._items = items

        def __aiter__(self):
            async def iterator():
                for item in self._items:
                    await asyncio.sleep(0)
                    yield item

            return iterator()

    disposer = ctx.effect(
        lambda: AsyncDisposerIterable([
            lambda: log.append("first"),
            lambda: log.append("second"),
        ]),
        "t27-async-iterable",
    )
    assert ctx.fiber.get_effects() == [{"label": "t27-async-iterable", "children": []}]

    await disposer()
    assert log == ["second", "first"]
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_t28_failing_async_iterable_rolls_back_and_rejects_disposer():
    """T28: an async-iterable failure rolls back and rejects the public disposer.

    Reference: the fiber.ts `_execute` asyncIterator promise rejects when the
    iterator throws, and the `effect` `wrapper.then` chain hands that rejection to
    the caller while the collected disposers are disposed.
    """
    ctx = Context()
    log = []

    class FailingAsyncIterable:
        def __aiter__(self):
            async def iterator():
                yield lambda: log.append("collected")
                await asyncio.sleep(0)
                raise RuntimeError("async iterable failed")

            return iterator()

    disposer = ctx.effect(lambda: FailingAsyncIterable(), "t28-failing")

    with pytest.raises(RuntimeError, match="async iterable failed"):
        await disposer()

    assert log == ["collected"]
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_t29_async_iterable_non_disposer_item_is_an_invalid_effect():
    """T29: async-iterable products go through `safeCollect` like sync ones.

    Reference: the fiber.ts `_execute` asyncIterator branch feeds every awaited
    `iter.next()` value to `safeCollect`, so a value that is neither a disposer
    nor null rejects the effect with `TypeError('Invalid effect')` after the
    collected disposers have been disposed.
    """
    ctx = Context()
    log = []

    class BadAsyncIterable:
        def __aiter__(self):
            async def iterator():
                yield lambda: log.append("collected")
                await asyncio.sleep(0)
                yield 42

            return iterator()

    disposer = ctx.effect(lambda: BadAsyncIterable(), "t29-invalid-async")

    with pytest.raises(TypeError, match="Invalid effect"):
        await disposer()

    assert log == ["collected"]
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_t30_apply_iterator_terminal_value_is_collected():
    """T30: the iterator's terminal value goes through `safeCollect`.

    Reference: fiber.ts `_execute` calls `safeCollect(result.value)` *before*
    checking `result.done`, so a generator that returns a non-null value fails
    the fiber and disposes the disposers it already produced.
    """
    ctx = Context()
    log = []

    class TerminalValuePlugin(Plugin):
        name = "terminal_value_plugin"

        def apply(self, c: Context):
            yield lambda: log.append("collected")
            return 7

    fiber = ctx.plugin(TerminalValuePlugin)
    assert fiber.state == FiberState.FAILED
    assert isinstance(fiber.error, TypeError)
    assert "Invalid effect" in str(fiber.error)
    assert log == ["collected"]

    # a plain `return` (null) stays legal
    ctx2 = Context()
    log2 = []

    class NullTerminalPlugin(Plugin):
        name = "null_terminal_plugin"

        def apply(self, c: Context):
            yield lambda: log2.append("kept")
            return

    fiber2 = ctx2.plugin(NullTerminalPlugin)
    assert fiber2.state == FiberState.ACTIVE
    assert fiber2.get_effects() == []

    await fiber2.dispose()
    assert log2 == ["kept"]

