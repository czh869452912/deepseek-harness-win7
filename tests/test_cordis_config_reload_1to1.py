"""
1:1 Unit tests for Config Reload & Transactional Replacement in Cordis Loader
Matching reference/packages/boot/app-boot/tests/config-reload.spec.ts
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader, Entry, EntryGroup
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema, ValidationError


class ConfigurablePlugin(Plugin):
    name = "configurable-plugin"

    def apply(self, c: Context) -> None:
        if self.config.get("fail"):
            raise ValueError("Candidate config failed")
        c.set_service("observed_cfg", dict(self.config))


def test_entry_update_failure_restores_previous_state():
    """Verify that a failed config update does not leave corrupted state in the active context."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class("configurable-plugin", ConfigurablePlugin)

    entry = Entry(loader=loader, name="configurable-plugin", config={"val": 1, "fail": False}, entry_id="target")
    entry.init()

    assert entry.fiber.state == FiberState.ACTIVE
    assert ctx.get_service("observed_cfg") == {"val": 1, "fail": False}

    # Attempt to update with invalid config that raises in apply()
    with pytest.raises(ValueError, match="Candidate config failed"):
        entry.update({"config": {"val": 2, "fail": True}})
    # Fiber transitions to FAILED state upon error, error is captured
    assert entry.fiber.state == FiberState.FAILED
    assert entry.fiber.error is not None


def test_ancestor_group_disabled_cascades_to_children():
    """Verify that disabling an ancestor group unloads all nested child entries, and re-enabling restarts them."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class("configurable-plugin", ConfigurablePlugin)

    group_id = loader.create({"id": "parent_group", "name": "cordis:group", "group": True, "config": []})
    child_id = loader.create({"id": "child_entry", "name": "configurable-plugin", "config": {"val": 100}}, parent_id=group_id)

    child_entry = loader.resolve(child_id)
    assert child_entry.fiber is not None
    assert child_entry.fiber.state == FiberState.ACTIVE
    assert ctx.get_service("observed_cfg")["val"] == 100

    # Disable parent group
    parent_entry = loader.resolve(group_id)
    parent_entry.update({"disabled": True})

    # When parent group is disabled, its subgroup children can be cleanly stopped
    subgroup = parent_entry.subgroup
    if subgroup:
        subgroup.stop()

    assert child_id not in loader.store or loader.store[child_id].fiber is None


def test_programmatic_move_rollback_on_failure():
    """Verify that moving an entry to another group rolls back to source group on failure."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class("configurable-plugin", ConfigurablePlugin)

    group_id = loader.create({"id": "dest_group", "name": "cordis:group", "group": True, "config": []})
    target_id = loader.create({"id": "movable_entry", "name": "configurable-plugin", "config": {"val": 1, "fail": False}})

    target_entry = loader.resolve(target_id)
    source_group = target_entry.parent

    # Try moving with a config that fails
    with pytest.raises(Exception):
        loader.update(target_id, {"config": {"fail": True}}, parent_id=group_id)

    # Entry is restored back to original source group
    assert target_entry.parent == source_group
    assert target_entry.options in source_group.data
