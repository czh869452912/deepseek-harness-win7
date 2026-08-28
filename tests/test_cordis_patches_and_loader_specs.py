"""
Comprehensive unit tests for Cordis Config Patches & Loader System
Matching reference/vendor/include/src/index.ts and packages/boot/app-boot/tests/user-patches.spec.ts.
"""

import sys
import pytest
from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader, apply_entry_patches, eval_condition
from dsh.cordis.plugin import Plugin


def test_apply_entry_patches_empty_returns_clone():
    """Returns deep clone unchanged when patches is None or empty list."""
    base = [{"id": "entry-1", "name": "pkg-1", "config": {"key": "val"}}]
    assert apply_entry_patches(base, None) == base
    assert apply_entry_patches(base, []) == base
    assert apply_entry_patches(base, []) is not base


def test_apply_entry_patches_top_level_insert():
    """Inserts new entries at top level when id is omitted."""
    base = [{"id": "entry-1", "name": "pkg-1"}]
    patches = [
        {"insert": [{"id": "entry-2", "name": "pkg-2"}, {"id": "entry-3", "name": "pkg-3"}]}
    ]
    res = apply_entry_patches(base, patches)
    assert len(res) == 3
    assert res[0]["id"] == "entry-1"
    assert res[1]["id"] == "entry-2"
    assert res[2]["id"] == "entry-3"


def test_apply_entry_patches_group_insert():
    """Inserts new entries into target group config array."""
    base = [
        {
            "id": "my-group",
            "name": "cordis:group",
            "group": True,
            "config": [{"id": "inner-1", "name": "pkg-inner-1"}]
        }
    ]
    patches = [
        {"id": "my-group", "insert": [{"id": "inner-2", "name": "pkg-inner-2"}]}
    ]
    res = apply_entry_patches(base, patches)
    assert len(res) == 1
    assert len(res[0]["config"]) == 2
    assert res[0]["config"][0]["id"] == "inner-1"
    assert res[0]["config"][1]["id"] == "inner-2"


def test_apply_entry_patches_sequential_multi_layer():
    """
    Index what a patch added so a LATER patch in the SAME list can target it.
    Matching reference/vendor/include/src/index.ts#applyEntryPatches lines 96-101.
    """
    base = [{"id": "entry-1", "name": "pkg-1"}]
    patches = [
        # Patch 1: insert new group
        {
            "insert": [
                {
                    "id": "inserted-group",
                    "name": "cordis:group",
                    "group": True,
                    "config": [{"id": "nested-a", "name": "pkg-a", "config": {"count": 1}}]
                }
            ]
        },
        # Patch 2: override nested-a inside inserted-group
        {"id": "nested-a", "config": {"count": 99}},
        # Patch 3: insert another entry into inserted-group
        {"id": "inserted-group", "insert": [{"id": "nested-b", "name": "pkg-b"}]}
    ]
    res = apply_entry_patches(base, patches)
    assert len(res) == 2
    grp = res[1]
    assert grp["id"] == "inserted-group"
    assert len(grp["config"]) == 2
    assert grp["config"][0]["id"] == "nested-a"
    assert grp["config"][0]["config"]["count"] == 99
    assert grp["config"][1]["id"] == "nested-b"


def test_apply_entry_patches_warnings():
    """Verify warning callbacks on missing ID, missing target, or name mismatch."""
    base = [{"id": "entry-1", "name": "pkg-1", "config": {"v": 1}}]
    warnings = []

    def warn(msg: str, *args: Any):
        warnings.append(msg % args if args else msg)

    patches = [
        # 1. Non-insert patch without id
        {"config": {"v": 2}},
        # 2. Target not found
        {"id": "non-existent", "config": {"v": 3}},
        # 3. Name mismatch
        {"id": "entry-1", "name": "wrong-name", "config": {"v": 4}},
    ]

    res = apply_entry_patches(base, patches, warn=warn)
    # Entry-1 was NOT mutated
    assert res[0]["config"]["v"] == 1
    assert len(warnings) == 3
    assert "id is required" in warnings[0]
    assert "entry 'non-existent' not found" in warnings[1]
    assert "name mismatch for 'entry-1'" in warnings[2]


def test_eval_condition_various_syntax():
    """Verify eval_condition for string expressions and process.platform mappings."""
    assert eval_condition(True) is True
    assert eval_condition(False) is False
    assert eval_condition(None) is False
    assert eval_condition("") is False

    # Platform checks
    if sys.platform == "win32":
        assert eval_condition("sys.platform == 'win32'") is True
        assert eval_condition("process.platform === 'win32'") is True
        assert eval_condition("!!js process.platform === 'win32'") is True
        assert eval_condition("process.platform !== 'win32'") is False
    else:
        assert eval_condition("sys.platform != 'win32'") is True


def test_loader_load_from_dict_with_patches():
    """Verify Loader.load_from_dict properly applies patches before mounting plugins."""
    ctx = Context()
    loaded = []

    class PluginA(Plugin):
        name = "pkg-a"
        def apply(self, c: Context) -> None:
            loaded.append(("pkg-a", self.config.get("val")))

    class PluginB(Plugin):
        name = "pkg-b"
        def apply(self, c: Context) -> None:
            loaded.append(("pkg-b", self.config.get("val")))

    loader = Loader(ctx)
    loader.register_plugin("pkg-a", PluginA)
    loader.register_plugin("pkg-b", PluginB)

    raw_config = [
        {"id": "plugin-a", "name": "pkg-a", "config": {"val": 10}}
    ]
    patches = [
        {"id": "plugin-a", "config": {"val": 100}},
        {"insert": [{"id": "plugin-b", "name": "pkg-b", "config": {"val": 200}}]}
    ]

    loader.load_from_dict(raw_config, patches=patches)

    assert ("pkg-a", 100) in loaded
    assert ("pkg-b", 200) in loaded
