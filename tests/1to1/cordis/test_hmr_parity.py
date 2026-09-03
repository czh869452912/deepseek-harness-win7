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
