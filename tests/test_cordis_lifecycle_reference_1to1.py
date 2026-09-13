"""
Direct 1:1 port of reference/packages/extensions/tool-cordis/tests/cordis-lifecycle.spec.ts.
Tests Cordis effect ownership, reentrant restarts, synchronous and asynchronous setup failure rollbacks,
single-shot disposers, and child publication lifecycle boundaries.
"""

import asyncio
import inspect

import pytest
from typing import Any, Dict, List, Optional

from dsh.cordis.context import Context
from dsh.cordis.fiber import CordisError, Fiber, FiberState
from dsh.cordis.plugin import Plugin


@pytest.mark.asyncio
async def test_reentrant_owner_restart_awaits_setup_plus_cleanup():
    """it('makes an effect visible to a reentrant owner restart and awaits setup plus cleanup')"""
    ctx = Context()
    setup_gate = asyncio.Future()
    cleanup_gate = asyncio.Future()
    cleanup_started = asyncio.Future()
    restarted: Optional[Any] = None
    setup_finished = False
    cleanup_finished = False

    async def _effect_body():
        nonlocal restarted, setup_finished, cleanup_finished
        restarted = ctx.fiber.restart()
        await setup_gate
        setup_finished = True

        async def _cleanup():
            nonlocal cleanup_finished
            if not cleanup_started.done():
                cleanup_started.set_result(None)
            await cleanup_gate
            cleanup_finished = True

        return _cleanup

    ctx.effect(_effect_body, "reentrant-restart")

    settled = False

    async def _track_restart():
        nonlocal settled
        if restarted:
            await restarted
        settled = True

    track_task = asyncio.create_task(_track_restart())
    await asyncio.sleep(0.01)
    assert settled is False

    setup_gate.set_result(None)
    await cleanup_started
    assert setup_finished is True
    await asyncio.sleep(0.01)
    assert settled is False

    cleanup_gate.set_result(None)
    if restarted:
        await restarted
    await track_task
    assert cleanup_finished is True
    assert ctx.fiber.get_effects() == []


def test_rolls_back_collected_cleanup_when_setup_throws_synchronously():
    """it('rolls back collected cleanup and its owner-list entry when setup throws synchronously')"""
    ctx = Context()
    cleanups = 0

    def failing_generator():
        nonlocal cleanups
        yield lambda: setattr(failing_generator, "cleaned", True)
        cleanups += 1
        raise RuntimeError("setup failed")

    with pytest.raises(RuntimeError, match="setup failed"):
        ctx.effect(failing_generator, "throwing-setup")

    assert getattr(failing_generator, "cleaned", False) is True
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_reentrant_restart_awaits_async_rollback_after_sync_failure():
    """it('makes a reentrant owner restart await asynchronous rollback after synchronous setup failure')"""
    ctx = Context()
    cleanup_gate = asyncio.Future()
    cleanup_started = asyncio.Future()
    restarted: Optional[Any] = None

    def failing_generator():
        nonlocal restarted
        async def _async_cleanup():
            if not cleanup_started.done():
                cleanup_started.set_result(None)
            await cleanup_gate

        yield _async_cleanup
        restarted = ctx.fiber.restart()
        raise RuntimeError("setup failed after restart")

    with pytest.raises(RuntimeError, match="setup failed after restart"):
        ctx.effect(failing_generator, "reentrant-throw")

    await cleanup_started
    settled = False

    async def _track():
        nonlocal settled
        if restarted:
            await restarted
        settled = True

    track_task = asyncio.create_task(_track())
    await asyncio.sleep(0.01)
    assert settled is False

    cleanup_gate.set_result(None)
    if restarted:
        await restarted
    await track_task
    assert ctx.fiber.get_effects() == []


def test_ordinary_teardown_synchronous_and_disposer_single_shot():
    """it('keeps ordinary teardown synchronous and the public disposer single-shot')"""
    ctx = Context()
    cleanups = 0

    def _setup():
        def _cleanup():
            nonlocal cleanups
            cleanups += 1
        return _cleanup

    dispose = ctx.effect(_setup, "sync-effect")
    assert cleanups == 0

    dispose()
    assert cleanups == 1

    dispose()
    assert cleanups == 1
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_rejects_cleanup_time_registration_while_restart_unloading():
    """it('rejects cleanup-time registration while a restart is unloading')"""
    ctx = Context()
    registration_error = None

    def _setup():
        def _cleanup():
            nonlocal registration_error
            try:
                ctx.effect(lambda: lambda: None, "too-late")
            except Exception as e:
                registration_error = e
        return _cleanup

    ctx.effect(_setup, "restart-cleanup")

    await ctx.fiber.restart()
    assert isinstance(registration_error, CordisError)
    assert registration_error.code == "INACTIVE_EFFECT"
    assert ctx.fiber.state == FiberState.ACTIVE
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_effect_registration_while_pending_and_loading():
    """it('keeps effect registration legal while child fibers are PENDING and LOADING')"""
    ctx = Context()
    pending_cleanup = []
    loading_cleanup = []

    def on_plugin(fiber: Fiber):
        if fiber.name != "state-probe" or fiber.uid is None:
            return
        # Upstream asserts the state at publication time: `expect(fiber.state).toBe(PENDING)`.
        assert fiber.state == FiberState.PENDING
        fiber.ctx.effect(lambda: lambda: pending_cleanup.append(True), "pending-effect")

    ctx.on("internal/plugin", on_plugin)

    class StateProbePlugin(Plugin):
        name = "state-probe"
        def apply(self, inner: Context) -> None:
            assert inner.fiber.state == FiberState.LOADING
            inner.effect(lambda: lambda: loading_cleanup.append(True), "loading-effect")

    fiber = await ctx.registry.plugin(StateProbePlugin())
    await fiber.dispose()

    assert pending_cleanup == [True]
    assert loading_cleanup == [True]


@pytest.mark.asyncio
async def test_resolves_dependencies_added_by_internal_plugin():
    """it('resolves dependencies that internal/plugin adds before child activation')"""
    ctx = Context()
    ctx.set_service("late-inject", {"key": "val"})
    apply_calls = 0

    def on_plugin(fiber: Fiber):
        if fiber.name != "loader-shaped" or fiber.uid is None:
            return
        fiber.inject["late-inject"] = None

    ctx.on("internal/plugin", on_plugin)

    class LoaderShapedPlugin(Plugin):
        name = "loader-shaped"
        def apply(self, c: Context) -> None:
            nonlocal apply_calls
            apply_calls += 1

    fiber = await ctx.registry.plugin(LoaderShapedPlugin())
    assert apply_calls == 1
    assert fiber.state == FiberState.ACTIVE


def test_rolls_back_when_internal_plugin_throws():
    """it('rolls back parent and runtime ownership when internal/plugin publication throws')

    The disposer owns the rollback: `fiber.ts` constructor calls `void
    Promise.resolve(this.dispose()).catch(...)` with no event loop in sight, so the
    parent-owned `ctx.plugin()` effect and the runtime registration must both be gone
    afterwards. A synchronous caller (no running loop) drains the teardown in the call.
    """
    ctx = Context()
    state: Dict[str, Any] = {}

    class PublicationFailurePlugin(Plugin):
        name = "publication-failure"
        def apply(self, c: Context) -> None:
            pass

    def on_plugin(fiber: Fiber):
        if fiber.name != "publication-failure":
            return
        if fiber.uid is None:
            return
        state["fiber"] = fiber
        state["runtime"] = fiber.runtime
        raise RuntimeError("publication failed")

    ctx.on("internal/plugin", on_plugin)

    plugin = PublicationFailurePlugin()
    with pytest.raises(RuntimeError, match="publication failed"):
        ctx.registry.plugin(plugin)

    assert ctx.registry.has(plugin) is False
    fiber = state["fiber"]
    assert fiber.uid is None
    assert fiber.state == FiberState.DISPOSED
    assert state["runtime"].fibers == []
    labels = [effect["label"] for effect in ctx.fiber.get_effects()]
    assert "ctx.plugin()" not in labels


@pytest.mark.asyncio
async def test_rolls_back_publication_failure_with_a_running_loop():
    """it('rolls back parent and runtime ownership when internal/plugin publication throws')
    (loop mode): a running loop schedules the teardown instead of draining it in the
    call, so the parent-owned effect and runtime record settle on the loop.
    """
    ctx = Context()
    state: Dict[str, Any] = {}

    class PublicationFailurePlugin(Plugin):
        name = "publication-failure-loop"
        def apply(self, c: Context) -> None:
            pass

    def on_plugin(fiber: Fiber):
        if fiber.name != "publication-failure-loop" or fiber.uid is None:
            return
        state["fiber"] = fiber
        raise RuntimeError("publication failed")

    ctx.on("internal/plugin", on_plugin)

    plugin = PublicationFailurePlugin()
    with pytest.raises(RuntimeError, match="publication failed"):
        ctx.registry.plugin(plugin)

    await asyncio.sleep(0)
    assert ctx.registry.has(plugin) is False
    assert state["fiber"].uid is None
    assert state["fiber"].state == FiberState.DISPOSED
    labels = [effect["label"] for effect in ctx.fiber.get_effects()]
    assert "ctx.plugin()" not in labels


@pytest.mark.asyncio
async def test_contains_teardown_notification_failures_so_peers_complete():
    """it('contains teardown notification failures so ownership cleanup and peers complete')"""
    ctx = Context()
    errors: List[Any] = []
    ctx.logger.error = lambda *args: errors.append(args[0])
    observed: List[str] = []

    def throwing_observer(fiber: Fiber) -> None:
        if fiber.name == "contained-teardown" and fiber.uid is None:
            raise RuntimeError("broken teardown observer")

    def counting_observer(fiber: Fiber) -> None:
        if fiber.name == "contained-teardown" and fiber.uid is None:
            observed.append("disposed")

    ctx.on("internal/plugin", throwing_observer)
    ctx.on("internal/plugin", counting_observer)

    class ContainedTeardownPlugin(Plugin):
        name = "contained-teardown"

        def apply(self, c: Context) -> None:
            pass

    child = await ctx.plugin(ContainedTeardownPlugin())
    child_disposer = child.dispose()
    assert inspect.isawaitable(child_disposer)
    assert await child_disposer is None

    assert observed == ["disposed"]
    assert len(errors) == 1
    assert str(errors[0]) == "broken teardown observer"
    assert child.uid is None


@pytest.mark.asyncio
async def test_loading_parent_joins_child_cleanup_started_before_unload_snapshot():
    """it('makes a LOADING parent join child cleanup started before its unload snapshot')"""
    ctx = Context()
    cleanup_gate = asyncio.Future()
    cleanup_started = asyncio.Future()
    state: Dict[str, Any] = {}

    def on_plugin(fiber: Fiber) -> None:
        if fiber.name != "loading-child" or fiber.uid is None:
            return
        state["child"] = fiber

        async def cleanup() -> None:
            if not cleanup_started.done():
                cleanup_started.set_result(None)
            await cleanup_gate

        fiber.ctx.effect(lambda: cleanup, "loading-child-cleanup")
        state["owner_disposal"] = asyncio.ensure_future(state["owner"].dispose())
        state["child_disposal"] = asyncio.ensure_future(fiber.dispose())

    ctx.on("internal/plugin", on_plugin)

    class LoadingChildPlugin(Plugin):
        name = "loading-child"

        def apply(self, c: Context) -> None:
            pass

    class LoadingOwnerPlugin(Plugin):
        name = "loading-owner"

        def apply(self, c: Context) -> None:
            state["owner"] = c.fiber
            c.plugin(LoadingChildPlugin())

    owner_mount = ctx.plugin(LoadingOwnerPlugin())

    await cleanup_started
    settled = False

    async def track() -> None:
        nonlocal settled
        await state["owner_disposal"]
        settled = True

    track_task = asyncio.create_task(track())
    await asyncio.sleep(0.01)
    assert settled is False

    cleanup_gate.set_result(None)
    await asyncio.gather(state["owner_disposal"], state["child_disposal"], owner_mount)
    await track_task
    assert state["child"].uid is None
    assert state["owner"].uid is None


@pytest.mark.asyncio
async def test_parent_disposal_during_publication_awaits_unpublished_child():
    """it('lets parent disposal during internal/plugin await the unpublished child to quiescence')"""
    ctx = Context()
    state: Dict[str, Any] = {}
    cleanup_gate = asyncio.Future()
    cleanup_started = asyncio.Future()
    cleanup_finished = False
    child_apply_calls = 0

    class OwnerPlugin(Plugin):
        name = "owner"

        def apply(self, c: Context) -> None:
            state["owner_ctx"] = c

    owner = await ctx.plugin(OwnerPlugin())

    def pending_child_cleanup(fiber: Fiber) -> None:
        if fiber.name != "child" or fiber.uid is None:
            return
        assert fiber.state == FiberState.PENDING

        async def cleanup() -> None:
            nonlocal cleanup_finished
            if not cleanup_started.done():
                cleanup_started.set_result(None)
            await cleanup_gate
            cleanup_finished = True

        fiber.ctx.effect(lambda: cleanup, "pending-child-cleanup")

    def parent_disposal(fiber: Fiber) -> None:
        if fiber.name != "child" or fiber.uid is None:
            return
        state["parent_disposal"] = asyncio.ensure_future(owner.dispose())

    ctx.on("internal/plugin", pending_child_cleanup)
    ctx.on("internal/plugin", parent_disposal)

    class ChildPlugin(Plugin):
        name = "child"

        def apply(self, c: Context) -> None:
            nonlocal child_apply_calls
            child_apply_calls += 1

    child = state["owner_ctx"].plugin(ChildPlugin())

    await cleanup_started
    settled = False

    async def track() -> None:
        nonlocal settled
        await state["parent_disposal"]
        settled = True

    track_task = asyncio.create_task(track())
    await asyncio.sleep(0.01)
    assert settled is False

    cleanup_gate.set_result(None)
    await state["parent_disposal"]
    await track_task
    assert cleanup_finished is True
    assert child_apply_calls == 0
    assert child.uid is None
    assert child.state == FiberState.DISPOSED


@pytest.mark.asyncio
async def test_direct_child_disposal_retires_the_parent_owned_effect():
    """Parent ownership: `this.dispose` is the parent-owned `ctx.plugin()` effect
    disposer (fiber.ts:265-297). Disposing a child therefore removes that
    registration from the parent (`Fiber.getEffects`, fiber.ts:568) instead of
    leaving a stale owner entry, and a later parent unload cannot dispose the
    child a second time.
    """
    ctx = Context()
    teardowns: List[str] = []

    class ChildPlugin(Plugin):
        name = "owned-child"
        def apply(self, c: Context) -> None:
            c.effect(lambda: (lambda: teardowns.append("child")), "child-effect")

    child = await ctx.plugin(ChildPlugin())
    assert [effect["label"] for effect in ctx.fiber.get_effects()] == ["ctx.plugin()"]

    await child.dispose()

    assert child.state == FiberState.DISPOSED
    assert teardowns == ["child"]
    assert ctx.fiber.get_effects() == []
    assert ctx.registry.has(ChildPlugin) is False

    # A parent unload must not re-run the disposed child's teardown.
    await ctx.fiber.dispose()
    assert teardowns == ["child"]

@pytest.mark.asyncio
async def test_mount_reports_loading_and_defers_the_plugin_body():
    """fiber.ts `_reload` crosses `await Promise.resolve()` before it resolves config
    and executes, so `ctx.plugin()` returns a LOADING fiber whose body has not run.
    """
    ctx = Context()
    applied = []
    statuses = []

    class LoadWindowPlugin(Plugin):
        name = "load-window-probe"

        def apply(self, c: Context) -> None:
            # fiber.ts `_reload` keeps the framework status while the body runs.
            assert c.fiber.state == FiberState.LOADING
            applied.append(True)

    def on_status(fiber: Fiber, old_state: int) -> None:
        if fiber.name == "load-window-probe":
            statuses.append((old_state, fiber.state))

    ctx.on("internal/status", on_status)

    fiber = ctx.plugin(LoadWindowPlugin)

    # Immediately after the mount: the LOADING status is published and no plugin
    # code has run yet.
    assert fiber.state == FiberState.LOADING
    assert applied == []
    assert statuses == [(FiberState.PENDING, FiberState.LOADING)]

    await fiber.await_settled()

    assert applied == [True]
    assert fiber.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_disposal_before_the_checkpoint_skips_the_plugin_body():
    """fiber.ts `_reload` re-checks its epoch after the initial microtask: a disposer
    queued before that checkpoint invalidates the load, so the body never runs and the
    fiber settles as DISPOSED with its parent-owned registration retired.
    """
    ctx = Context()
    applied = []

    class CancelBeforeLoadPlugin(Plugin):
        name = "cancel-before-load"

        def apply(self, c: Context) -> None:
            applied.append(True)

    fiber = ctx.plugin(CancelBeforeLoadPlugin)
    assert fiber.state == FiberState.LOADING

    await fiber.dispose()

    assert applied == []
    assert fiber.state == FiberState.DISPOSED
    assert [effect["label"] for effect in ctx.fiber.get_effects()] == []

    # the cancelled load never runs later either
    await asyncio.sleep(0)
    assert applied == []


@pytest.mark.asyncio
async def test_nested_mount_activates_after_its_parent_body_returns():
    """A child mounted from a parent body activates at its own checkpoint, so the
    parent body returns first and the child's body runs after it.
    """
    ctx = Context()
    order = []

    class NestedChildPlugin(Plugin):
        name = "nested-child"

        def apply(self, c: Context) -> None:
            order.append("child")

    class NestedParentPlugin(Plugin):
        name = "nested-parent"

        def apply(self, c: Context) -> None:
            order.append("parent-start")
            child = c.plugin(NestedChildPlugin)
            order.append(("child-state-in-parent", child.state))
            order.append("parent-end")

    parent = ctx.plugin(NestedParentPlugin)

    await parent.await_settled()
    assert parent.state == FiberState.ACTIVE
    # The parent body saw a LOADING child and ran to completion first, so the
    # child's own body starts strictly after `parent-end`.
    assert order[:3] == [
        "parent-start",
        ("child-state-in-parent", FiberState.LOADING),
        "parent-end",
    ]

    await asyncio.sleep(0)
    assert order.count("child") == 1
    assert order.index("child") > order.index("parent-end")


def test_loop_less_mount_runs_inline():
    """Python 3.8 has no ambient microtask queue outside a running loop.

    A loop-less caller therefore has no checkpoint to cross and keeps the port's
    inline activation; the deferred path above requires a running loop. The
    upstream event order is nevertheless preserved: PENDING -> LOADING is
    published before the body runs and LOADING -> ACTIVE after it, and the
    settled fiber is ACTIVE with exactly one application, so entering a loop
    afterwards cannot re-run the body or mount the plugin twice.
    """
    ctx = Context()
    applied = []
    statuses = []

    class LoopLessPlugin(Plugin):
        name = "loop-less"

        def apply(self, c: Context) -> None:
            applied.append(True)

    ctx.on("internal/status", lambda fiber, old_state: statuses.append((old_state, fiber.state)))

    fiber = ctx.plugin(LoopLessPlugin)

    assert applied == [True]
    assert fiber.state == FiberState.ACTIVE
    assert statuses == [
        (FiberState.PENDING, FiberState.LOADING),
        (FiberState.LOADING, FiberState.ACTIVE),
    ]
    assert fiber.inertia is None

    # The settled fiber stays stable: waiting on it from inside a loop is a
    # no-op and no second activation is started for the executed load.
    async def _settle() -> int:
        await fiber.await_settled()
        return fiber.state

    assert asyncio.run(_settle()) == FiberState.ACTIVE
    assert applied == [True]


@pytest.mark.asyncio
async def test_loading_status_reports_the_dependency_snapshot_before_execution():
    """fiber.ts `_reload` runs `this.store = { ...this._store }` before its first
    `await Promise.resolve()`, and `_setEpoch` publishes LOADING only once that
    prefix returned. An `internal/status` observer for PENDING -> LOADING
    therefore already sees the dependency snapshot while no plugin code has run.
    """
    ctx = Context()
    observed = {}

    class SnapshotProvider(Plugin):
        name = "snapshot-provider"

        def apply(self, c: Context) -> None:
            c.provide("snapshot-svc", {"v": 1})

    class SnapshotConsumer(Plugin):
        name = "snapshot-consumer"
        inject = ["snapshot-svc"]

        def apply(self, c: Context) -> None:
            observed["body"] = "ran"
            return lambda: observed.__setitem__("cleanup", True)

    def on_status(fiber: Fiber, old_state: int) -> None:
        if fiber.name != "snapshot-consumer":
            return
        if old_state == FiberState.PENDING and fiber.state == FiberState.LOADING:
            store = fiber.store
            observed["store_at_loading"] = None if store is None else sorted(store)
            observed["body_at_loading"] = observed.get("body")

    ctx.on("internal/status", on_status)

    provider = await ctx.plugin(SnapshotProvider)
    consumer = ctx.plugin(SnapshotConsumer)

    # The snapshot is taken before the LOADING status is published, and the body
    # runs only at the event-loop checkpoint.
    assert observed["store_at_loading"] == ["snapshot-svc"]
    assert observed["body_at_loading"] is None
    assert "body" not in observed
    assert consumer.state == FiberState.LOADING

    await consumer.await_settled()

    assert observed["body"] == "ran"
    assert consumer.state == FiberState.ACTIVE

    # Losing the dependency unloads the activated body and its effect.
    await provider.dispose()
    await consumer.await_settled()

    assert observed.get("cleanup") is True
    assert consumer.state == FiberState.PENDING


def _state_names():
    """Return the FiberState name for each state value."""
    return {value: name for name, value in vars(FiberState).items() if isinstance(value, int)}


@pytest.mark.asyncio
async def test_ordinary_effect_stays_owner_visible_until_cleanup_settles():
    """
    fiber.ts `finalizeDisposal` -> `removeWrapper`: an ordinary effect remains
    listed by its owner while its asynchronous cleanup is in flight, a repeated
    disposal joins that cleanup, and retirement happens only at settlement.
    """
    ctx = Context()
    release = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_count = 0

    async def cleanup():
        nonlocal cleanup_count
        cleanup_count += 1
        cleanup_started.set()
        await release.wait()

    def disposer():
        return cleanup()

    def labels():
        return [meta["label"] if isinstance(meta, dict) else meta.label for meta in ctx.fiber.get_effects()]

    dispose = ctx.fiber.effect(lambda: disposer, "owner-visible")
    assert labels() == ["owner-visible"]

    first = dispose()
    await cleanup_started.wait()
    assert labels() == ["owner-visible"]

    second = dispose()
    assert second is first

    release.set()
    await first
    assert cleanup_count == 1
    assert labels() == []


@pytest.mark.asyncio
async def test_owner_unload_joins_effect_cleanup_started_by_another_caller():
    """
    fiber.ts `runDisposable` + `effectInertia`: an owner fiber unload that calls
    a wrapper whose asynchronous cleanup another caller already started joins
    that cleanup instead of disposing the effect a second time.
    """
    ctx = Context()
    release = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_finished = False
    cleanup_count = 0

    async def cleanup():
        nonlocal cleanup_count, cleanup_finished
        cleanup_count += 1
        cleanup_started.set()
        await release.wait()
        cleanup_finished = True

    def disposer():
        return cleanup()

    dispose = ctx.fiber.effect(lambda: disposer, "joined")
    first = dispose()
    await cleanup_started.wait()
    assert first is not None

    restarted = ctx.fiber.restart()
    release.set()
    await restarted
    assert cleanup_count == 1
    assert cleanup_finished is True
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_startup_failure_unloads_collected_effects_and_publishes_loading_unloading_failed():
    """
    fiber.ts `_reload` catch + `_unload`: a startup failure records the error,
    invalidates the epoch, unloads the effects collected before the failure, and
    publishes LOADING -> UNLOADING -> FAILED; awaiting the fiber rethrows the
    failure only after that cleanup settled.
    """
    ctx = Context()
    statuses = []
    cleanups = []
    state_names = _state_names()

    ctx.on(
        "internal/status",
        lambda fiber, old_state: statuses.append(
            (state_names.get(old_state, old_state), state_names.get(fiber.state, fiber.state))
        ),
    )

    async def failing_plugin(fiber_ctx):
        fiber_ctx.effect(lambda: lambda: cleanups.append("collected"), label="collected")
        await asyncio.sleep(0)
        raise RuntimeError("startup failed")

    fiber = ctx.plugin(failing_plugin)
    with pytest.raises(RuntimeError, match="startup failed"):
        await fiber.await_settled()

    assert statuses == [
        ("PENDING", "LOADING"),
        ("LOADING", "UNLOADING"),
        ("UNLOADING", "FAILED"),
    ]
    assert cleanups == ["collected"]
    assert fiber.state == FiberState.FAILED
    assert fiber.error is not None
    assert fiber.get_effects() == []
