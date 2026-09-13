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

    fiber = ctx.registry.plugin(StateProbePlugin())
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

    fiber = ctx.registry.plugin(LoaderShapedPlugin())
    assert apply_calls == 1
    assert fiber.state == FiberState.ACTIVE


def test_rolls_back_when_internal_plugin_throws():
    """it('rolls back parent and runtime ownership when internal/plugin publication throws')"""
    ctx = Context()

    class PublicationFailurePlugin(Plugin):
        name = "publication-failure"
        def apply(self, c: Context) -> None:
            pass

    def on_plugin(fiber: Fiber):
        if fiber.name == "publication-failure":
            raise RuntimeError("publication failed")

    ctx.on("internal/plugin", on_plugin)

    plugin = PublicationFailurePlugin()
    with pytest.raises(RuntimeError, match="publication failed"):
        ctx.registry.plugin(plugin)

    assert ctx.registry.has(plugin) is False

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
