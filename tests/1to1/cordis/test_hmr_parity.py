"""
1:1 parity unit test suite for dsh/cordis/hmr.py matching reference/vendor/hmr/src/index.ts.
These exact-path watch tests disable unrelated recursive repository watches.
Covers:
- T1: register_config applies present file immediately once
- T2: config file creation (add) and deletion (unlink) triggers refresh
- T5: register_config duplicate path raises ValueError
- T6: register_config on inactive HMR raises RuntimeError
- T8: hmr/change event is not emitted during config refresh
"""

import asyncio
import gc
import os
import tempfile
import warnings
import pytest

from dsh.cordis.context import Context
from dsh.cordis.hmr import ConfigWatcherService


@pytest.mark.asyncio
async def test_hmr_fiber_disposal_stops_polling_and_joins_refresh(tmp_path):
    """Service.init teardown closes the watcher and awaits refreshTasks."""
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService

    ctx = Context()
    await ctx.plugin(Loader)
    await ctx.plugin(TimerService)
    fiber = await ctx.plugin(ConfigWatcherService, {"debounce": 10, "root": []})
    hmr = ctx.get('hmr')
    polling = hmr._poll_task
    started, release = asyncio.Event(), asyncio.Event()
    async def refresh():
        started.set()
        await release.wait()
    config = tmp_path / 'owned.yaml'
    config.write_text('key: value\n', encoding='utf-8')
    await hmr.register_config(str(config), refresh)
    await asyncio.wait_for(started.wait(), 2)
    disposing = asyncio.ensure_future(fiber.dispose())
    try:
        await asyncio.sleep(0)
        assert not disposing.done()
        release.set()
        await asyncio.wait_for(disposing, 2)
        assert not hmr._running
        assert polling.done()
        assert all(task.done() for task in hmr._refresh_tasks)
        assert not hmr._configs
        assert ctx.get('hmr') is None
    finally:
        release.set()
        await asyncio.wait_for(ctx.fiber.dispose(), 2)


@pytest.mark.asyncio
async def test_t1_register_config_applies_present_file_once():
    """T1: register_config on existing file immediately runs refresh_fn once."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    ctx.set_service("hmr", hmr)

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"key: value\n")
        tmp_path = f.name

    try:
        call_count = [0]

        def refresh():
            call_count[0] += 1

        disp = hmr.register_config(tmp_path, refresh)
        # Yield to event loop to allow initial task to run
        await asyncio.sleep(0.05)

        assert call_count[0] == 1

        disp()
    finally:
        settlement = hmr.teardown()
        if settlement is not None:
            await settlement
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_t2_config_file_creation_and_unlink_trigger():
    """T2: creating (add) and deleting (unlink) an uncreated file triggers refresh."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 20, "root": []})
    ctx.set_service("hmr", hmr)

    tmp_dir = tempfile.mkdtemp()
    target_file = os.path.join(tmp_dir, "nonexistent.yaml")

    try:
        events = []

        def refresh():
            events.append("refresh")

        disp = hmr.register_config(target_file, refresh)
        await asyncio.sleep(0.05)
        # Initially doesn't exist, so no initial refresh
        assert len(events) == 0

        # 1. Create file (add)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("content: 1\n")

        await asyncio.sleep(0.1)
        assert len(events) >= 1

        # 2. Delete file (unlink)
        os.remove(target_file)
        events.clear()

        await asyncio.sleep(0.1)
        assert len(events) >= 1

        disp()
    finally:
        settlement = hmr.teardown()
        if settlement is not None:
            await settlement
        if os.path.exists(target_file):
            os.remove(target_file)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)


def test_t5_register_config_duplicate_raises():
    """T5: register_config with duplicate path raises ValueError."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        tmp_path = f.name

    try:
        hmr.register_config(tmp_path, lambda: None)
        with pytest.raises(ValueError) as exc:
            hmr.register_config(tmp_path, lambda: None)
        assert "already registered" in str(exc.value)
    finally:
        hmr.teardown()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_t6_register_config_inactive_raises():
    """T6: register_config after teardown raises RuntimeError."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    hmr.teardown()

    with pytest.raises(RuntimeError) as exc:
        hmr.register_config("any_path.yaml", lambda: None)
    assert "not active" in str(exc.value)


@pytest.mark.asyncio
async def test_t8_hmr_change_not_emitted_for_config_refresh():
    """T8: config file refresh does not emit hmr/change event."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    ctx.set_service("hmr", hmr)

    change_emitted = [False]

    def on_change(file):
        change_emitted[0] = True

    ctx.on("hmr/change", on_change)

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"foo: bar\n")
        tmp_path = f.name

    try:
        hmr.register_config(tmp_path, lambda: None)
        await asyncio.sleep(0.05)
        assert change_emitted[0] is False
    finally:
        settlement = hmr.teardown()
        if settlement is not None:
            await settlement
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_t9_refresh_disposing_root_does_not_wait_for_its_own_disposer():
    """refreshConfig completes before its root-owned registration is disposed.

    The outer settlement caller joins root cleanup. The refresh task must not
    wait for root cleanup, which itself waits for the registration's refresh.
    """
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    ctx.set_service("hmr", hmr)

    cleanup_started = asyncio.Event()
    release = asyncio.Event()
    log = []

    async def cleanup():
        cleanup_started.set()
        await release.wait()
        log.append("cleanup")

    ctx.effect(lambda: lambda: cleanup(), label="root-teardown")

    def refresh():
        ctx.root.fiber.schedule_settlement(ctx.root.fiber.dispose())

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"key: value\n")
        tmp_path = f.name

    try:
        registration = hmr.register_config(tmp_path, refresh)
        await asyncio.wait_for(cleanup_started.wait(), 2)
        assert log == []

        release.set()
        # Root disposal joins its registration internally. An external caller
        # joins the owned settlement after refresh yields, never from the pass.
        await asyncio.wait_for(ctx.fiber.await_settled(), 2)
        assert log == ["cleanup"]
        assert ctx.fiber.settlement_tasks() == []
    finally:
        settlement = hmr.teardown()
        if settlement is not None:
            await settlement
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_teardown_settlement_is_fiber_owned_and_leaves_no_pending_task():
    """Teardown is the `Service.init` disposer, so its settlement has an owner.

    `reference/vendor/hmr/src/index.ts:199-205` owns the cleanup as the
    `Service.init` disposer, which the owning fiber awaits. A direct
    `teardown()` inside a running loop cannot await it, so the fiber records
    the settlement (`Fiber.schedule_settlement`) and the caller joins the
    returned task. Nothing may outlive that join: an unowned
    `loop.create_task` was destroyed with the loop while still pending.
    """
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    poll = hmr._poll_task
    assert poll is not None and not poll.done()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settlement = hmr.teardown()

        # Owned before it settles: it is joined by the fiber, not by the loop.
        assert settlement is not None
        assert settlement in ctx.fiber.settlement_tasks()
        await settlement
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        gc.collect()

    assert pending == []
    assert ctx.fiber.settlement_tasks() == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []
    assert hmr._running is False
    assert poll.done()
    assert hmr._configs == {}
    assert hmr._modules == {}


@pytest.mark.asyncio
async def test_teardown_settlement_is_joined_when_the_caller_drops_it():
    """A dropped teardown settlement is still joined by its owner.

    `fiber.ts` lets a caller start a teardown and drop the returned promise
    because the microtask queue keeps driving it. CPython drives a coroutine
    only while a task holds it, so the fiber owns the settlement and
    `await_settled()` joins it -- the same contract as a dropped root-fiber
    disposal.
    """
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    settlement = hmr.teardown()

    assert settlement is not None
    assert settlement in ctx.fiber.settlement_tasks()
    await ctx.fiber.await_settled()
    pending = [
        task for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]

    assert pending == []
    assert ctx.fiber.settlement_tasks() == []
    assert hmr._running is False



GATE_PLUGIN_SOURCE = '''\
from dsh.cordis.plugin import Plugin


class GatePlugin(Plugin):
    id = "gate-plugin"
    def apply(self, ctx):
        gate = self.config["gate"]

        async def cleanup():
            gate["entered"].set()
            await gate["release"].wait()

        ctx.effect(lambda: cleanup, label="gate-cleanup")
'''


@pytest.mark.asyncio
async def test_module_registration_disposal_owns_its_join_of_the_running_pass(tmp_path):
    """Disposing a module registration joins its own in-flight pass through its owner.

    `reference/vendor/hmr/src/index.ts:177-181` awaits a registration's running
    refresh before retiring it, and CPython drives that join only while a task
    holds it, so the fiber records it -- the same contract as the HMR teardown
    settlement. The pass belongs to the module watch: a live config
    registration for the same path keeps its own serialization state
    (`index.ts:93-95`).
    """
    import importlib.util

    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    module = tmp_path / "watched.py"
    module.write_text(GATE_PLUGIN_SOURCE, encoding="utf-8")
    gate = {"entered": asyncio.Event(), "release": asyncio.Event()}
    config_calls = []

    async def refresh():
        config_calls.append(1)

    # A live config registration for the same path owns its state independently.
    config_registration = hmr.register_config(str(module), refresh)
    await asyncio.sleep(0.05)
    assert config_calls == [1]
    canonical = list(hmr._configs)[0]
    config_owner = hmr._configs[canonical]
    config_state = hmr._config_refreshes.get(config_owner)
    assert config_state is not None

    spec = importlib.util.spec_from_file_location("watched_gate_module", str(module))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    plugin_cls = mod.GatePlugin
    await ctx.plugin(plugin_cls, {"gate": gate})

    registration = hmr.register_module(canonical, plugin_cls)
    # Bump the watched file so the poll loop starts a genuine module pass, which
    # blocks in the replaced fiber's asynchronous cleanup.
    bumped = os.path.getmtime(str(module)) + 2.0
    module.write_text(GATE_PLUGIN_SOURCE, encoding="utf-8")
    os.utime(str(module), (bumped, bumped))
    await asyncio.wait_for(gate["entered"].wait(), 3)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        registration()

        # The join of the module pass is owned before it settles.
        assert len(ctx.fiber.settlement_tasks()) == 1
        # The live config registration keeps the serialization state it owns.
        assert hmr._config_refreshes.get(config_owner) is config_state

        gate["release"].set()
        await ctx.fiber.await_settled()
        assert ctx.fiber.settlement_tasks() == []

        disposal = config_registration()
        await disposal
        assert disposal.disposed
        assert hmr._config_refreshes == {}

        settlement = hmr.teardown()
        if settlement is not None:
            await settlement
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        gc.collect()

    assert pending == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []
    assert hmr._modules == {}
    assert hmr._module_refreshes == {}

@pytest.mark.asyncio
async def test_module_registration_disposal_leaves_a_live_config_watch_armed_once(tmp_path):
    """Disposing a module registration must not re-arm the live config watch.

    The config loop reads a missing staleness entry as an add event, so the
    module registration cannot retire the entry the config watch for the same
    path still owns: doing so refreshes the config a second time without a
    change and re-creates the refresh state the disposal just retired.
    """
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    module = tmp_path / "watched.py"
    module.write_text("x = 1\n", encoding="utf-8")
    calls = []
    started, release = asyncio.Event(), asyncio.Event()

    async def refresh():
        calls.append(1)
        started.set()
        await release.wait()

    await hmr.register_config(str(module), refresh)
    await asyncio.wait_for(started.wait(), 2)
    canonical = list(hmr._configs)[0]
    registration = hmr.register_module(canonical, None)

    registration()
    release.set()
    await ctx.fiber.await_settled()
    # Ten poll ticks at the 20 ms floor: a retired entry reads as an add event.
    await asyncio.sleep(0.2)
    settlement = hmr.teardown()
    if settlement is not None:
        await settlement

    assert len(calls) == 1
    assert hmr._module_refreshes == {}
    assert hmr._config_refreshes == {}


@pytest.mark.asyncio
async def test_shared_path_live_change_while_refresh_pending(tmp_path):
    """A disposed module registration must not release a pending config refresh.

    `reference/vendor/hmr/src/index.ts:93-95,296-323` keys the refresh state by
    the config registration and coalesces a later event into the dirty loop of
    the pass that is already running. A genuine change on the shared path while
    the first callback is still blocked must therefore stay dirty work, never a
    second concurrent callback.
    """
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10, "root": []})
    module = tmp_path / "watched.py"
    module.write_text("x = 1\n", encoding="utf-8")
    started, release = asyncio.Event(), asyncio.Event()
    calls, active, peak = [], [0], [0]

    async def refresh():
        calls.append(1)
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        started.set()
        try:
            await release.wait()
        finally:
            active[0] -= 1

    registration = hmr.register_config(str(module), refresh)
    await asyncio.wait_for(started.wait(), 2)
    canonical = list(hmr._configs)[0]
    unregister = hmr.register_module(canonical, None)
    unregister()

    # A genuine config event while the initial callback is still blocked.
    bumped = os.path.getmtime(canonical) + 2.0
    with open(canonical, "w", encoding="utf-8") as f:
        f.write("x = 2\n")
    os.utime(canonical, (bumped, bumped))
    await asyncio.sleep(0.25)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # One callback at a time: the pending refresh is still serialized.
        assert len(calls) == 1
        assert peak[0] == 1

        release.set()
        for _ in range(40):
            if len(calls) == 2 and not hmr._refresh_tasks:
                break
            await asyncio.sleep(0.05)

        # The event observed during the pending pass ran serially inside it.
        assert len(calls) == 2
        assert peak[0] == 1

        disposal = registration()
        await disposal
        assert disposal.disposed
        assert hmr._config_refreshes == {}

        settlement = hmr.teardown()
        if settlement is not None:
            await settlement
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        gc.collect()

    assert pending == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []
    assert hmr._module_refreshes == {}
    assert hmr._config_refreshes == {}
