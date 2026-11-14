"""
Unit tests for Loader Entry and EntryGroup transactions matching reference/vendor/loader/src/config/entry.ts & tree.ts.
Tests options updates, enable/disable toggling, duplicate id validation, and atomic rollbacks.
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader, Entry, EntryTree, EntryGroup
from dsh.cordis.plugin import Plugin


class SampleServicePlugin(Plugin):
    name = "sample-service"

    def apply(self, c: Context) -> None:
        c.set_service("sample", {"running": True, "count": self.config.get("count", 0)})


def test_entry_update_config_and_state_toggle():
    """Verify that updating an Entry's options updates its fiber config and handles disabled toggling."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class("sample-service", SampleServicePlugin)

    entry = Entry(loader=loader, name="sample-service", config={"count": 1}, entry_id="sample_01")
    entry.init()

    assert entry.fiber is not None
    assert entry.fiber.state == FiberState.ACTIVE
    assert ctx.get_service("sample")["count"] == 1

    # Update config
    entry.update({"config": {"count": 10}})
    assert entry.fiber.state == FiberState.ACTIVE
    assert ctx.get_service("sample")["count"] == 10

    # Toggle disabled -> true (unloads fiber)
    entry.update({"disabled": True})
    assert entry.fiber is None
    assert ctx.get_service("sample") is None

    # Toggle disabled -> false (starts fiber)
    entry.update({"disabled": False})
    assert entry.fiber is not None
    assert entry.fiber.state == FiberState.ACTIVE
    assert ctx.get_service("sample")["count"] == 10


def test_entry_group_duplicate_ids_use_last_row_without_reverting_desired_list():
    """Fixed Source maps explicit ids to the last row and retains the input list."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class('sample-service', SampleServicePlugin)
    group = loader.root
    duplicate_batch = [
        {'id':'dup1','name':'sample-service','config':{'count':1}},
        {'id':'dup1','name':'sample-service','config':{'count':2}},
    ]
    group.update(duplicate_batch)
    assert group.data is duplicate_batch
    assert list(loader.store) == ['dup1']
    assert loader.store['dup1'].fiber.effectiveConfig == {'count':2}
    import asyncio
    asyncio.run(ctx.fiber.dispose())


def test_entry_tree_nested_resolve_and_remove():
    """Verify that EntryTree can resolve entries and remove them cleanly."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class("sample-service", SampleServicePlugin)

    eid = loader.create({"id": "root_entry", "name": "sample-service", "config": {"count": 5}})
    resolved = loader.resolve("root_entry")
    assert resolved.id == "root_entry"

    loader.remove("root_entry")
    with pytest.raises(KeyError):
        loader.resolve("root_entry")
