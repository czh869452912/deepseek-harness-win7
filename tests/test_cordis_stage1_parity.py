"""
Unit tests verifying Cordis Stage 1 parity improvements:
- internal/dispatch 4-argument parity
- internal/listener fiber hooks redirection
- Fiber clean empty epoch and async inertia barrier
- apply_entry_patches hierarchical config patching
"""

import asyncio
import pytest
from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState, INACTIVE_EPOCH
from dsh.cordis.loader import apply_entry_patches
from dsh.cordis.plugin import Plugin


class DummyService:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.val = "dummy_val"


def test_internal_dispatch_four_arguments_parity():
    """Verify internal/dispatch receives (mode, name, args, caller_ctx) matching TS EventsService."""
    ctx = Context()
    dispatches = []

    def on_dispatch(mode: str, name: str, args: List[Any], caller_ctx: Any):
        dispatches.append({"mode": mode, "name": name, "args": args, "ctx": caller_ctx})

    ctx.on("internal/dispatch", on_dispatch, global_listener=True)

    ctx.emit("test/event", 123, "hello", key="value")

    assert len(dispatches) >= 1
    found = next((d for d in dispatches if d["name"] == "test/event"), None)
    assert found is not None
    assert found["mode"] == "emit"
    assert found["args"] == [123, "hello"]
    assert found["ctx"] is ctx


def test_internal_listener_fiber_hooks_redirection():
    """Verify internal/listener captures non-global internal/update into fiber._hooks."""
    ctx = Context()
    updates = []

    class UpdatePlugin(Plugin):
        name = "update-plugin"
        inject = []

        def apply(self, c: Context) -> None:
            def on_update(config: Any, no_save: bool, next_fn: Any):
                updates.append(config)
                return next_fn(config)

            c.on("internal/update", on_update)

    fiber = ctx.registry.plugin(UpdatePlugin())
    assert "internal/update" in fiber._hooks
    assert fiber._hooks["internal/update"].length == 1

    # Trigger internal/update on the fiber's context
    res = fiber.ctx.waterfall_sync("internal/update", {"key": "val1"}, False, lambda cfg: cfg)
    assert res == {"key": "val1"}
    assert updates == [{"key": "val1"}]


def test_fiber_epoch_clean_empty_string():
    """Verify that a plugin with empty inject has epoch == '' matching TS Cordis."""
    ctx = Context()

    class StandalonePlugin(Plugin):
        name = "standalone"
        inject = []

        def apply(self, c: Context) -> None:
            pass

    fiber = ctx.registry.plugin(StandalonePlugin())
    assert fiber.state == FiberState.ACTIVE
    assert fiber.epoch == ""


@pytest.mark.asyncio
async def test_fiber_async_inertia_barrier():
    """Verify that async effect disposers attach to inertia and await_settled waits for them."""
    ctx = Context()
    cleaned = []

    class AsyncEffectPlugin(Plugin):
        name = "async-effect"
        inject = []

        def apply(self, c: Context) -> None:
            async def async_disposer():
                await asyncio.sleep(0.05)
                cleaned.append("done")

            c.effect(lambda: async_disposer, label="async_disposer")

    fiber = ctx.registry.plugin(AsyncEffectPlugin())
    assert fiber.state == FiberState.ACTIVE
    assert cleaned == []

    # Unload / restart
    fiber.restart()
    await fiber.await_settled()
    assert "done" in cleaned


def test_apply_entry_patches_hierarchical():
    """Verify apply_entry_patches matching TS reference/vendor/include/src/index.ts."""
    base_data = [
        {"id": "plugin-a", "name": "pkg-a", "config": {"timeout": 1000}},
        {
            "id": "group-1",
            "name": "cordis:group",
            "group": True,
            "config": [
                {"id": "nested-1", "name": "pkg-nested-1", "config": {"debug": False}}
            ]
        }
    ]

    patches = [
        # 1. Override existing root entry
        {"id": "plugin-a", "config": {"timeout": 5000}},
        # 2. Override nested entry
        {"id": "nested-1", "config": {"debug": True}},
        # 3. Insert into group
        {"id": "group-1", "insert": [{"id": "nested-2", "name": "pkg-nested-2"}]},
        # 4. Insert at root
        {"insert": [{"id": "plugin-b", "name": "pkg-b"}]}
    ]

    result = apply_entry_patches(base_data, patches)

    # Verify immutability of base_data
    assert base_data[0]["config"]["timeout"] == 1000
    assert len(base_data) == 2

    # Verify patched results
    assert result[0]["id"] == "plugin-a"
    assert result[0]["config"]["timeout"] == 5000
    assert len(result) == 3
    assert result[2]["id"] == "plugin-b"

    group_entry = result[1]
    assert group_entry["group"] is True
    assert len(group_entry["config"]) == 2
    assert group_entry["config"][0]["id"] == "nested-1"
    assert group_entry["config"][0]["config"]["debug"] is True
    assert group_entry["config"][1]["id"] == "nested-2"
