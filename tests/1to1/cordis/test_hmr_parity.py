"""
1:1 parity unit test suite for dsh/cordis/hmr.py matching reference/vendor/hmr/src/index.ts.
Covers:
- T1: register_config applies present file immediately once
- T2: config file creation (add) and deletion (unlink) triggers refresh
- T5: register_config duplicate path raises ValueError
- T6: register_config on inactive HMR raises RuntimeError
- T8: hmr/change event is not emitted during config refresh
"""

import asyncio
import os
import tempfile
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
    fiber = await ctx.plugin(ConfigWatcherService, {"debounce": 10})
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
    hmr = ConfigWatcherService(ctx, {"debounce": 10})
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
        hmr.teardown()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_t2_config_file_creation_and_unlink_trigger():
    """T2: creating (add) and deleting (unlink) an uncreated file triggers refresh."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 20})
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
        hmr.teardown()
        if os.path.exists(target_file):
            os.remove(target_file)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)


def test_t5_register_config_duplicate_raises():
    """T5: register_config with duplicate path raises ValueError."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10})

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
    hmr = ConfigWatcherService(ctx, {"debounce": 10})
    hmr.teardown()

    with pytest.raises(RuntimeError) as exc:
        hmr.register_config("any_path.yaml", lambda: None)
    assert "not active" in str(exc.value)


@pytest.mark.asyncio
async def test_t8_hmr_change_not_emitted_for_config_refresh():
    """T8: config file refresh does not emit hmr/change event."""
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10})
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
        hmr.teardown()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_t9_refresh_disposing_root_does_not_wait_for_its_own_disposer():
    """refreshConfig completes before its root-owned registration is disposed.

    The outer settlement caller joins root cleanup. The refresh task must not
    wait for root cleanup, which itself waits for the registration's refresh.
    """
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 10})
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
        hmr.teardown()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
