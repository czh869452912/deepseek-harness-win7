"""
1:1 Unit tests for ConfigWatcherService / Hmr in Cordis
Matching reference/vendor/hmr/src/index.ts
"""

import asyncio
import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.cordis.hmr import ConfigWatcherService


@pytest.mark.asyncio
async def test_config_watcher_debounced_reload():
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 50})

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml") as f:
        f.write("initial: true\n")
        tmp_path = f.name

    try:
        reload_count = 0
        def on_reload():
            nonlocal reload_count
            reload_count += 1

        unregister = hmr.register_config(tmp_path, on_reload)

        # Trigger modification
        await asyncio.sleep(0.05)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("updated: true\n")

        # Wait for poll cycle
        await asyncio.sleep(0.3)
        assert reload_count >= 1

        unregister()
    finally:
        hmr.teardown()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_config_watcher_failure_event_broadcast():
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {"debounce": 50})

    failed_notifications = []
    async def on_fail(filename, error):
        failed_notifications.append((filename, str(error)))

    ctx.on("hmr/config-update-failed", on_fail)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml") as f:
        f.write("a: 1\n")
        tmp_path = f.name

    try:
        def bad_reload():
            raise ValueError("Parse syntax error")

        unregister = hmr.register_config(tmp_path, bad_reload)

        # Trigger update
        await asyncio.sleep(0.05)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("a: 2\n")

        await asyncio.sleep(0.3)
        assert len(failed_notifications) >= 1
        assert "Parse syntax error" in failed_notifications[0][1]

        unregister()
    finally:
        hmr.teardown()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
