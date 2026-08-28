"""
Direct 1:1 port of reference/packages/extensions/tool-cordis/tests/cordis-lifecycle.spec.ts.
Tests Cordis effect ownership, reentrant restarts, synchronous and asynchronous setup failure rollbacks,
single-shot disposers, and child publication lifecycle boundaries.
"""

import asyncio
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
        if fiber.name != "state-probe" or fiber.uid is None or fiber.state != FiberState.PENDING:
            return
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
