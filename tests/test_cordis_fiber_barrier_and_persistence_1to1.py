"""
Unit tests for Cordis Fiber setup rollback on failure, ValidationError path formatting,
EntryTree atomic persistence with sort_keys, and Service.filter isolation matching reference TS Cordis.
"""

import os
import pytest
import tempfile
import yaml
from typing import Any, Dict, List

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState, ValidationError, resolve_config
from dsh.cordis.loader import Loader, Entry, EntryTree, sort_keys
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def test_fiber_effect_setup_rollback_on_failure():
    """Verify that when a generator effect setup throws synchronously, collected cleanups roll back immediately."""
    ctx = Context()
    cleanups = []

    def failing_generator():
        yield lambda: cleanups.append("step1")
        yield lambda: cleanups.append("step2")
        raise ValueError("setup exploded")

    with pytest.raises(ValueError, match="setup exploded"):
        ctx.effect(failing_generator, label="failing-generator")

    assert cleanups == ["step2", "step1"]
    assert ctx.fiber.get_effects() == []


def test_validation_error_paths_formatting():
    """Verify ValidationError formats issues with dot paths matching TS ValidationError."""
    issues = [
        {"message": "port must be between 1 and 65535", "path": ["server", "port"]},
        {"message": "secret cannot be empty", "path": ["auth", "jwt", "secret"]},
        {"message": "general configuration failure"},
    ]
    err = ValidationError(issues)
    err_str = str(err)

    assert "invalid config:" in err_str
    assert "- port must be between 1 and 65535 (at server.port)" in err_str
    assert "- secret cannot be empty (at auth.jwt.secret)" in err_str
    assert "- general configuration failure" in err_str


def test_sort_keys_ordering():
    """Verify sort_keys places id, name first, config last, and sorted keys in middle."""
    raw = {
        "config": {"debug": True},
        "disabled": False,
        "name": "@deepseek-ai/dsh-persona",
        "isolate": {"db": True},
        "id": "pers_01",
        "inject": ["fs", "llm"],
    }
    sorted_dict = sort_keys(raw)
    keys_list = list(sorted_dict.keys())

    assert keys_list[0] == "id"
    assert keys_list[1] == "name"
    assert keys_list[-1] == "config"
    assert keys_list[2:-1] == ["disabled", "inject", "isolate"]


def test_entry_tree_atomic_write_persistence():
    """Verify EntryTree.write() dumps sorted configuration cleanly to YAML file."""
    ctx = Context()
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "preset.yaml")

        tree = EntryTree(ctx, filepath=config_path)
        tree.create({
            "id": "item1",
            "name": "plugin-alpha",
            "config": {"foo": "bar"},
            "disabled": False,
        })
        tree.create({
            "id": "item2",
            "name": "plugin-beta",
            "config": {"count": 42},
        })

        assert os.path.exists(config_path)

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == "item1"
        assert data[0]["name"] == "plugin-alpha"
        assert data[1]["id"] == "item2"
        assert data[1]["name"] == "plugin-beta"


def test_service_filter_isolation():
    """Verify that Service.filter checks matching isolation scope labels."""
    ctx = Context()

    class StorageService(Service):
        name = "storage"

    root_storage = StorageService(ctx)

    # In matching context (root), filter returns True
    assert root_storage.filter(ctx) is True

    # In isolated context for storage, filter returns False
    iso_ctx = ctx.isolate("storage")
    assert root_storage.filter(iso_ctx) is False
