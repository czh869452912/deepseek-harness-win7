"""
Comprehensive 1:1 Parity and Behavior Verification Tests for dsh/settings.
Tests multi-level config hierarchy, revision tracking, path mutations (update, replace, mutate),
secret redaction (redactSecrets), schema/validate checks, change event emission, and cold-start logic.
"""

import json
import os
import tempfile
import pytest
import yaml

from dsh.cordis.context import Context
from dsh.settings import (
    FileSettingsProvider,
    RedactedSecret,
    RedactedValue,
    SettingsConflictError,
    SettingsDescriptor,
    SettingsFilePlugin,
    SettingsProvider,
    SettingsService,
    apply_path_op,
    clone_json_shaped,
    deep_equal_json,
    install_settings_section,
    merge_layers,
    redact_secrets,
    resolve_spec,
    settings_namespace,
)
from dsh.settings.invariant import apply as apply_settings_invariant


def test_settings_namespace_validation():
    assert settings_namespace("llm") == "llm"
    assert settings_namespace("llm-deepseek") == "llm-deepseek"
    assert settings_namespace("general") == "general"

    with pytest.raises(TypeError):
        settings_namespace("Invalid_NS!")

    with pytest.raises(TypeError):
        settings_namespace("123-ns")


def test_deep_equal_json_and_merge_layers():
    # 1. deep_equal_json
    assert deep_equal_json({"a": 1, "b": [2, 3]}, {"b": [2, 3], "a": 1})
    assert not deep_equal_json({"a": 1}, {"a": 2})
    assert not deep_equal_json({"a": 1}, {"a": "1"})

    # 2. merge_layers multi-level recursive object merge
    under = {"a": {"x": 1, "y": 2}, "b": "base"}
    over = {"a": {"x": 10}, "c": "user"}
    merged = merge_layers(under, over)
    assert merged == {"a": {"x": 10, "y": 2}, "b": "base", "c": "user"}


def test_apply_path_op_and_clone_json_shaped():
    sec = {"a": {"b": 1, "c": 2}}

    # set nested path
    res = apply_path_op(sec, {"op": "set", "path": ["a", "b"], "value": 100})
    assert res == {"a": {"b": 100, "c": 2}}

    # unset nested path
    res2 = apply_path_op(sec, {"op": "unset", "path": ["a", "c"]})
    assert res2 == {"a": {"b": 1}}

    # clone_json_shaped validation
    clone = clone_json_shaped({"name": "test", "items": [1, 2, 3]}, lambda msg, p: TypeError(msg))
    assert clone == {"name": "test", "items": [1, 2, 3]}

    with pytest.raises(TypeError):
        clone_json_shaped({"fn": lambda: None}, lambda msg, p: TypeError(msg))


def test_multi_level_config_hierarchy():
    """
    Audit 1: Multi-level hierarchy:
    Schema defaults -> Preset Base -> User Settings -> Project Settings (.dsh/settings.yaml)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        user_settings_file = os.path.join(tmpdir, "user_settings.yaml")
        # User settings override
        with open(user_settings_file, "w", encoding="utf-8") as f:
            yaml.dump({"llm": {"model": "user-model"}}, f)

        # Create temporary project directory
        project_dir = os.path.join(tmpdir, "my_project")
        os.makedirs(os.path.join(project_dir, ".dsh"), exist_ok=True)
        project_settings_file = os.path.join(project_dir, ".dsh", "settings.yaml")
        with open(project_settings_file, "w", encoding="utf-8") as f:
            yaml.dump({"llm": {"base_url": "https://project.api.com"}}, f)

        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            ctx = Context()
            provider = FileSettingsProvider(ctx=ctx, config={"path": user_settings_file, "watch": False})

            def schema_fn(val):
                d = {"model": "schema-model", "base_url": "https://schema.api.com", "temperature": 0.7}
                if isinstance(val, dict):
                    d.update(val)
                return d

            # Register with Preset Base
            scope = provider.register("llm", schema=schema_fn, base={"temperature": 0.5})

            resolved = scope.get()
            # 1. Preset base (temperature: 0.5) over schema defaults (0.7)
            assert resolved["temperature"] == 0.5
            # 2. User settings (model: user-model) over preset base
            assert resolved["model"] == "user-model"
            # 3. Project settings (.dsh/settings.yaml base_url) over user settings
            assert resolved["base_url"] == "https://project.api.com"
        finally:
            os.chdir(old_cwd)


def test_revision_tracking_path_mutations_and_conflict_errors():
    """
    Audit 2: Revision tracking (revision number), update/replace/mutate, conflict errors
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "settings.yaml")
        ctx = Context()
        provider = FileSettingsProvider(ctx=ctx, config={"path": sf, "watch": False})
        scope = provider.register("llm", base={"model": "v0", "timeout": 30})

        assert provider.get_revision("llm") == 1

        # 1. update (merge)
        provider.update("llm", {"model": "v1"})
        assert scope.get()["model"] == "v1"
        assert scope.get()["timeout"] == 30
        assert provider.get_revision("llm") == 2

        # 2. replace (wholesale reset of user layer)
        provider.replace("llm", {"timeout": 60})
        assert scope.get()["model"] == "v0"  # fell back to base
        assert scope.get()["timeout"] == 60
        assert provider.get_revision("llm") == 3

        # 3. mutate (path ops)
        provider.mutate("llm", [
            {"op": "set", "path": ["model"], "value": "v2"},
            {"op": "set", "path": ["extra", "key"], "value": "val"},
        ])
        assert scope.get()["model"] == "v2"
        assert scope.get()["extra"]["key"] == "val"
        assert provider.get_revision("llm") == 4

        # 4. SettingsConflictError on stale expectedRevision
        with pytest.raises(SettingsConflictError) as exc_info:
            provider.update("llm", {"model": "stale"}, expected_revision=2)
        assert exc_info.value.code == "SETTINGS_CONFLICT"
        assert exc_info.value.expected == 2
        assert exc_info.value.actual == 4


def test_redact_secrets_and_describe():
    """
    Audit 2: redactSecrets and describe API
    """
    schema = {
        "type": "object",
        "properties": {
            "baseUrl": {"type": "string"},
            "apiKey": {"type": "string", "role": "secret"},
        },
    }
    value = {"baseUrl": "https://api.deepseek.com", "apiKey": "sk-secret-key-123"}

    redacted = redact_secrets(schema, value)
    assert redacted.value == {"baseUrl": "https://api.deepseek.com"}
    assert len(redacted.secrets) == 1
    assert redacted.secrets[0].path == ["apiKey"]
    assert redacted.secrets[0].set is True

    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "settings.yaml")
        ctx = Context()
        provider = FileSettingsProvider(ctx=ctx, config={"path": sf, "watch": False})
        provider.register("llm", schema=schema, base=value)

        descriptors = provider.describe({"redactSecrets": True})
        assert len(descriptors) == 1
        desc = descriptors[0]
        assert desc["ns"] == "llm"
        assert desc["value"] == {"baseUrl": "https://api.deepseek.com"}
        assert desc["secrets"] == [{"path": ["apiKey"], "set": True}]


def test_validation_and_event_emission():
    """
    Audit 2: Settings validation and change event emission
    """
    events = []

    def on_updated(ns, next_v, prev_v, source):
        events.append(("updated", ns, next_v, prev_v, source))

    def on_doc_updated(ns, rev):
        events.append(("doc_updated", ns, rev))

    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "settings.yaml")
        ctx = Context()
        ctx.on("settings/updated", on_updated)
        ctx.on("settings/document-updated", on_doc_updated)

        provider = FileSettingsProvider(ctx=ctx, config={"path": sf, "watch": False})

        def custom_validate(val):
            if isinstance(val, dict) and val.get("port", 80) < 1024:
                raise ValueError("port must be >= 1024")

        # 1. Validation failure at register() fails immediately
        with pytest.raises(ValueError):
            provider.register("server", base={"port": 80}, validate=custom_validate)

        scope = provider.register("server", base={"port": 8080}, validate=custom_validate)

        # 2. Validation failure at update() rejects before persisting
        with pytest.raises(ValueError):
            scope.update({"port": 80})
        assert scope.get()["port"] == 8080

        # 3. Valid update emits settings/updated and settings/document-updated
        scope.update({"port": 9000})
        assert scope.get()["port"] == 9000
        assert any(e[0] == "updated" and e[1] == "server" and e[4] == "update" for e in events)
        assert any(e[0] == "doc_updated" and e[1] == "server" for e in events)


def test_cold_start_loading_chain_cli_vs_web():
    """
    Audit 3: Cold-start config loading chain differences between CLI and Web UI mode
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "settings.yaml")
        ctx = Context()

        # 1. Plugin mount in CLI mode
        plugin = SettingsFilePlugin(config={"path": sf, "watch": False})
        plugin.apply(ctx)

        service = ctx.get("settings")
        assert service is not None
        assert service.writable is True
        assert service.document_path == os.path.abspath(sf)

        # 2. Web UI mode interaction helpers
        path = service.prepare_document()
        assert os.path.exists(path)

        descriptors = service.describe({"redactSecrets": True})
        assert isinstance(descriptors, list)


def test_install_settings_section():
    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "settings.yaml")
        ctx = Context()
        sf_plugin = SettingsFilePlugin(config={"path": sf, "watch": False})
        sf_plugin.apply(ctx)

        source_val = None
        changes_count = 0

        def set_source(fn):
            nonlocal source_val
            source_val = fn

        def on_change():
            nonlocal changes_count
            changes_count += 1

        entry = {"model": "entry-model"}
        install_settings_section(
            ctx,
            "llm",
            schema=None,
            entry=entry,
            hooks={"setSource": set_source, "onChange": on_change},
        )

        assert source_val is not None
        assert source_val()["model"] == "entry-model"
        assert changes_count == 1
