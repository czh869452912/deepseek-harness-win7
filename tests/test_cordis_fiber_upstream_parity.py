import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState


@pytest.mark.asyncio
async def test_effect_runs_setup_immediately_and_disposes_once_in_reverse_order():
    ctx = Context()
    calls = []

    def setup():
        calls.append("setup")
        return iter((lambda: calls.append("first"), lambda: calls.append("second")))

    dispose = ctx.effect(setup, "ordered")
    assert calls == ["setup"]

    await dispose()
    await dispose()
    assert calls == ["setup", "second", "first"]


@pytest.mark.asyncio
async def test_effect_does_not_guess_that_setup_is_already_a_disposer():
    ctx = Context()
    calls = []

    def cleanup():
        calls.append("setup-called")

    dispose = ctx.effect(cleanup, "ctx.on(event)")
    assert calls == ["setup-called"]
    await dispose()
    assert calls == ["setup-called"]


@pytest.mark.asyncio
async def test_effect_accepts_async_setup_and_async_iterable_disposers():
    ctx = Context()
    setup_gate = asyncio.Event()
    calls = []

    async def generated():
        yield lambda: calls.append("one")
        await setup_gate.wait()
        yield lambda: calls.append("two")

    def setup():
        calls.append("setup")
        return generated()

    dispose = ctx.effect(setup)
    disposal = asyncio.create_task(dispose())
    await asyncio.sleep(0)
    assert calls == ["setup"]
    assert not disposal.done()

    setup_gate.set()
    await disposal
    assert calls == ["setup", "two", "one"]


@pytest.mark.asyncio
async def test_effect_disposer_is_awaitable_completion():
    ctx = Context()
    gate = asyncio.Event()
    calls = []

    async def setup():
        await gate.wait()
        calls.append("ready")
        return lambda: calls.append("disposed")

    dispose = ctx.effect(setup)
    waiter = asyncio.ensure_future(dispose)
    await asyncio.sleep(0)
    assert not waiter.done()

    gate.set()
    returned = await waiter
    assert returned is dispose
    assert calls == ["ready"]

    await dispose()
    assert calls == ["ready", "disposed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, 0, "cleanup", object()])
async def test_effect_rejects_invalid_return_shapes(invalid):
    ctx = Context()
    with pytest.raises(TypeError, match="Invalid effect"):
        ctx.effect(lambda: invalid)


@pytest.mark.asyncio
async def test_sync_setup_failure_rolls_back_collected_disposers_in_reverse_order():
    ctx = Context()
    calls = []

    def setup():
        yield lambda: calls.append("first")
        yield lambda: calls.append("second")
        raise RuntimeError("load failed")

    with pytest.raises(RuntimeError, match="load failed"):
        ctx.effect(setup)
    assert calls == ["second", "first"]


@pytest.mark.asyncio
async def test_function_object_and_class_plugins_receive_context_and_config():
    ctx = Context()
    calls = []

    def function_plugin(plugin_ctx, config):
        calls.append(("function", plugin_ctx, config))

    class ObjectPlugin:
        id = "object-plugin"

        def apply(self, plugin_ctx, config):
            calls.append(("object", plugin_ctx, config))

    class ClassPlugin:
        id = "class-plugin"

        def __init__(self, plugin_ctx, config):
            calls.append(("class", plugin_ctx, config))

    function_fiber = ctx.registry.plugin(function_plugin, {"kind": "function"})
    object_fiber = ctx.registry.plugin(ObjectPlugin(), {"kind": "object"})
    class_fiber = ctx.registry.plugin(ClassPlugin, {"kind": "class"})

    await function_fiber
    await object_fiber
    await class_fiber

    assert [entry[0] for entry in calls] == ["function", "object", "class"]
    assert [entry[2] for entry in calls] == [
        {"kind": "function"},
        {"kind": "object"},
        {"kind": "class"},
    ]
    assert all(entry[1].fiber is fiber for entry, fiber in zip(
        calls, (function_fiber, object_fiber, class_fiber)
    ))


@pytest.mark.asyncio
async def test_async_plugin_setup_controls_inertia_state_and_failure_rollback():
    ctx = Context()
    gate = asyncio.Event()
    calls = []

    async def plugin(plugin_ctx, config):
        plugin_ctx.effect(lambda: lambda: calls.append("inner"))
        await gate.wait()
        calls.append(config["name"])
        raise RuntimeError("startup failed")

    fiber = ctx.registry.plugin(plugin, {"name": "async"})
    assert fiber.state == FiberState.LOADING
    gate.set()

    with pytest.raises(RuntimeError, match="startup failed"):
        await fiber
    assert fiber.state == FiberState.FAILED
    assert calls == ["async", "inner"]


@pytest.mark.asyncio
async def test_concurrent_dispose_joins_one_unload_and_logs_all_disposer_errors():
    ctx = Context()
    calls = []
    errors = []

    class Logger:
        def error(self, reason):
            errors.append(reason)

    ctx._services["logger"] = Logger()

    def plugin(plugin_ctx, _config):
        async def slow():
            await asyncio.sleep(0)
            calls.append("slow")
            raise RuntimeError("slow failed")

        def fast():
            calls.append("fast")
            raise ValueError("fast failed")

        plugin_ctx.effect(lambda: slow)
        plugin_ctx.effect(lambda: fast)

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    await asyncio.gather(fiber.dispose(), fiber.dispose())

    assert sorted(calls) == ["fast", "slow"]
    assert sorted(str(error) for error in errors) == ["fast failed", "slow failed"]
    assert fiber.state == FiberState.DISPOSED


@pytest.mark.asyncio
async def test_concurrent_restart_and_dispose_settle_as_disposed():
    ctx = Context()
    gate = asyncio.Event()
    calls = []

    def plugin(plugin_ctx, _config):
        calls.append("load")

        async def cleanup():
            calls.append("unload-start")
            await gate.wait()
            calls.append("unload-end")

        return cleanup

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    restart = asyncio.create_task(fiber.restart())
    await asyncio.sleep(0)
    dispose = asyncio.create_task(fiber.dispose())
    gate.set()
    await asyncio.gather(restart, dispose)

    assert fiber.state == FiberState.DISPOSED
    assert calls == ["load", "unload-start", "unload-end"]


@pytest.mark.asyncio
async def test_epoch_flip_during_load_drains_stale_load_then_reloads_latest_epoch():
    ctx = Context()
    calls = []

    def plugin(_plugin_ctx, _config):
        calls.append("load")

    fiber = ctx.registry.plugin(plugin, {})
    assert fiber.state == FiberState.LOADING
    fiber.set_epoch("new-epoch")

    await fiber
    assert calls == ["load"]
    assert fiber.epoch == "new-epoch"
    assert fiber.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_epoch_flip_during_unload_reloads_instead_of_sticking_unloading():
    ctx = Context()
    unloading = asyncio.Event()
    release = asyncio.Event()
    calls = []

    def plugin(_plugin_ctx, _config):
        calls.append("load")

        async def cleanup():
            unloading.set()
            await release.wait()
            calls.append("unload")

        return cleanup

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    fiber.set_epoch("__INACTIVE__")
    await unloading.wait()
    fiber.set_epoch("replacement")
    release.set()

    await fiber
    assert calls == ["load", "unload", "load"]
    assert fiber.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_failed_async_iterable_effect_auto_rolls_back_and_remains_observable():
    ctx = Context()
    rolled_back = asyncio.Event()

    async def setup():
        yield lambda: rolled_back.set()
        raise RuntimeError("effect setup failed")

    dispose = ctx.effect(setup, "failing-async-generator")
    with pytest.raises(RuntimeError, match="effect setup failed"):
        await dispose
    await asyncio.wait_for(rolled_back.wait(), timeout=1)

    assert "failing-async-generator" not in {
        effect["label"] for effect in ctx.fiber.get_effects()
    }
    with pytest.raises(RuntimeError, match="effect setup failed"):
        await dispose()


@pytest.mark.asyncio
async def test_cancelling_dispose_waiter_does_not_cancel_shared_cleanup():
    ctx = Context()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def cleanup():
        started.set()
        await release.wait()
        calls.append("disposed")

    dispose = ctx.effect(lambda: cleanup)
    first = asyncio.create_task(dispose())
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    await dispose()
    assert calls == ["disposed"]


@pytest.mark.asyncio
async def test_cleanup_cancelled_error_propagates_without_error_logging():
    ctx = Context()
    errors = []

    class Logger:
        def error(self, reason):
            errors.append(reason)

    ctx._services["logger"] = Logger()

    async def cleanup():
        raise asyncio.CancelledError()

    dispose = ctx.effect(lambda: cleanup)
    with pytest.raises(asyncio.CancelledError):
        await dispose()
    assert errors == []


def test_sync_setup_rollback_propagates_cleanup_cancellation_without_logging():
    ctx = Context()
    errors = []

    class Logger:
        def error(self, reason):
            errors.append(reason)

    ctx._services["logger"] = Logger()

    def cancel_cleanup():
        raise asyncio.CancelledError()

    def setup():
        yield cancel_cleanup
        raise RuntimeError("setup failed")

    with pytest.raises(asyncio.CancelledError):
        ctx.effect(setup, "sync-cancelled-rollback")
    assert errors == []
    assert "sync-cancelled-rollback" not in {
        effect["label"] for effect in ctx.fiber.get_effects()
    }


@pytest.mark.asyncio
async def test_sync_setup_failure_keeps_async_rollback_owner_visible_and_observed():
    ctx = Context()
    started = asyncio.Event()
    release = asyncio.Event()
    errors = []

    class Logger:
        def error(self, reason):
            errors.append(reason)

    ctx._services["logger"] = Logger()

    async def cleanup():
        started.set()
        await release.wait()
        raise RuntimeError("async rollback failed")

    def sync_cleanup():
        raise ValueError("sync rollback failed")

    def setup():
        yield cleanup
        yield sync_cleanup
        raise RuntimeError("sync setup failed")

    with pytest.raises(RuntimeError, match="sync setup failed"):
        ctx.effect(setup, "sync-failure-async-rollback")
    assert "sync-failure-async-rollback" in {
        effect["label"] for effect in ctx.fiber.get_effects()
    }

    owner_dispose = asyncio.create_task(ctx.fiber.dispose())
    await started.wait()
    assert not owner_dispose.done()
    release.set()
    await owner_dispose

    assert [str(error) for error in errors] == [
        "sync rollback failed",
        "async rollback failed",
    ]
    assert "sync-failure-async-rollback" not in {
        effect["label"] for effect in ctx.fiber.get_effects()
    }


@pytest.mark.asyncio
async def test_cancelling_restart_waiter_does_not_cancel_shared_transition():
    ctx = Context()
    unloading = asyncio.Event()
    release = asyncio.Event()
    loads = []

    def plugin(_plugin_ctx, _config):
        loads.append(len(loads) + 1)

        async def cleanup():
            unloading.set()
            await release.wait()

        return cleanup

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    first = asyncio.create_task(fiber.restart())
    await unloading.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    await fiber.restart()
    assert loads == [1, 2]
    assert fiber.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_cancelling_dispose_waiter_does_not_cancel_fiber_disposal():
    ctx = Context()
    started = asyncio.Event()
    release = asyncio.Event()

    def plugin(_plugin_ctx, _config):
        async def cleanup():
            started.set()
            await release.wait()

        return cleanup

    fiber = ctx.registry.plugin(plugin, {})
    await fiber
    first = asyncio.create_task(fiber.dispose())
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    await fiber.dispose()
    assert fiber.state == FiberState.DISPOSED


@pytest.mark.asyncio
async def test_cleanup_cancellation_settles_restart_lifecycle_for_retry():
    ctx = Context()
    cleanups = []

    def plugin(_plugin_ctx, _config):
        async def cleanup():
            cleanups.append("cleanup")
            if len(cleanups) == 1:
                raise asyncio.CancelledError()

        return cleanup

    fiber = ctx.registry.plugin(plugin, {})
    await fiber

    with pytest.raises(asyncio.CancelledError):
        await fiber.restart()
    await fiber.restart()

    assert fiber.inertia is None
    assert fiber.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_cleanup_cancellation_settles_dispose_lifecycle_for_retry():
    ctx = Context()
    cleanups = []

    def plugin(_plugin_ctx, _config):
        async def cleanup():
            cleanups.append("cleanup")
            if len(cleanups) == 1:
                raise asyncio.CancelledError()

        return cleanup

    fiber = ctx.registry.plugin(plugin, {})
    await fiber

    with pytest.raises(asyncio.CancelledError):
        await fiber.dispose()
    await fiber.dispose()

    assert fiber.inertia is None
    assert fiber.state == FiberState.DISPOSED


@pytest.mark.asyncio
async def test_async_plugin_startup_error_is_logged_once_and_cleanup_separately():
    ctx = Context()
    errors = []

    class Logger:
        def error(self, reason):
            errors.append(reason)

    ctx._services["logger"] = Logger()

    async def plugin(plugin_ctx, _config):
        async def cleanup():
            raise ValueError("cleanup failed")

        plugin_ctx.effect(lambda: cleanup)
        await asyncio.sleep(0)
        raise RuntimeError("startup failed")

    fiber = ctx.registry.plugin(plugin, {})
    with pytest.raises(RuntimeError, match="startup failed"):
        await fiber
    await asyncio.sleep(0)

    assert [str(error) for error in errors].count("startup failed") == 1
    assert [str(error) for error in errors].count("cleanup failed") == 1


@pytest.mark.asyncio
async def test_sync_plugin_starts_in_loading_and_reports_failure_from_await():
    ctx = Context()
    calls = []

    def good(_plugin_ctx, _config):
        calls.append("good")

    def bad(_plugin_ctx, _config):
        calls.append("bad")
        raise RuntimeError("sync startup failed")

    good_fiber = ctx.registry.plugin(good, {})
    bad_fiber = ctx.registry.plugin(bad, {})
    assert good_fiber.state == FiberState.LOADING
    assert bad_fiber.state == FiberState.LOADING
    assert calls == []

    await good_fiber
    with pytest.raises(RuntimeError, match="sync startup failed"):
        await bad_fiber
    assert calls == ["good", "bad"]
    assert bad_fiber.state == FiberState.FAILED


@pytest.mark.asyncio
async def test_restart_rebuilds_store_from_current_dependency_snapshot():
    ctx = Context()
    fiber = ctx.registry.plugin(lambda _ctx, _config: None, {})
    dependency = object()
    fiber._store["dependency"] = dependency
    await fiber
    first_store = fiber.store

    await fiber.restart()
    assert fiber.store == {"dependency": dependency}
    assert fiber.store is not first_store


@pytest.mark.asyncio
async def test_update_hot_starts_restart_before_returned_awaitable_is_awaited():
    ctx = Context()
    calls = []
    restarted = asyncio.Event()

    def plugin(_plugin_ctx, config):
        calls.append(config["version"])
        if config["version"] == 2:
            restarted.set()

    fiber = ctx.registry.plugin(plugin, {"version": 1})
    await fiber

    update = fiber.update({"version": 2})
    try:
        await asyncio.wait_for(restarted.wait(), timeout=1)
        assert calls == [1, 2]
        await update
    finally:
        close = getattr(update, "close", None)
        if callable(close):
            close()


@pytest.mark.asyncio
async def test_update_returned_awaitable_propagates_restart_failure():
    ctx = Context()

    def plugin(_plugin_ctx, config):
        if config["fail"]:
            raise RuntimeError("updated startup failed")

    fiber = ctx.registry.plugin(plugin, {"fail": False})
    await fiber

    update = fiber.update({"fail": True})
    with pytest.raises(RuntimeError, match="updated startup failed"):
        await update


@pytest.mark.asyncio
async def test_update_recovers_failed_fiber_with_new_config():
    ctx = Context()
    calls = []

    def plugin(_plugin_ctx, config):
        calls.append(config["value"])
        if config["value"] == "invalid":
            raise RuntimeError("invalid initial config")

    fiber = ctx.registry.plugin(plugin, {"value": "invalid"})
    with pytest.raises(RuntimeError, match="invalid initial config"):
        await fiber
    assert fiber.state == FiberState.FAILED

    result = fiber.update({"value": "valid"})
    assert result is None
    await fiber

    assert fiber.state == FiberState.ACTIVE
    assert fiber.config == {"value": "valid"}
    assert calls == ["invalid", "valid"]


@pytest.mark.asyncio
async def test_update_rechecks_pending_fiber_dependencies():
    ctx = Context()
    available = [False]
    ctx.provide("gate", object(), check=lambda: available[0])
    calls = []

    class Consumer:
        inject = ["gate"]

        def apply(self, _plugin_ctx, config):
            calls.append(config["value"])

    fiber = ctx.registry.plugin(Consumer(), {"value": "old"})
    assert fiber.state == FiberState.PENDING

    available[0] = True
    result = fiber.update({"value": "new"})
    assert result is None
    await fiber

    assert fiber.state == FiberState.ACTIVE
    assert calls == ["new"]


@pytest.mark.asyncio
async def test_parent_fiber_owns_child_disposal():
    ctx = Context()
    calls = []

    def child(plugin_ctx, _config):
        plugin_ctx.effect(lambda: lambda: calls.append("child-disposed"))

    fiber = ctx.registry.plugin(child, {})
    await fiber
    await ctx.fiber.dispose()
    assert calls == ["child-disposed"]


@pytest.mark.asyncio
async def test_plugin_publication_has_owned_uid_before_initial_refresh_and_dispose_event_is_preserved():
    ctx = Context()
    parent_ctx = ctx.extend()
    events = []

    def observe_plugin(fiber):
        events.append((fiber, fiber.uid, fiber.state, fiber.parent))

    ctx.on("internal/plugin", observe_plugin, global_listener=True)
    fiber = ctx.registry.plugin(
        lambda _plugin_ctx, _config: None,
        parent_ctx=parent_ctx,
    )

    assert events == [(fiber, fiber.uid, FiberState.PENDING, parent_ctx)]
    await fiber
    assert len([event for event in events if event[0] is fiber]) == 1

    await fiber.dispose()
    assert events == [
        (fiber, events[0][1], FiberState.PENDING, parent_ctx),
        (fiber, None, FiberState.DISPOSED, parent_ctx),
    ]
