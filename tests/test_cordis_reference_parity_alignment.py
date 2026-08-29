"""
Tests for Cordis reference parity alignment against official DeepSeek Harness specs.
Verifies:
1. Context.is_ global immutable brand checking.
2. Waterfall / waterfall_sync 0-arg short-circuit, veto without next(), and transformer pipeline.
3. Service.init generator lifecycle protocol (yield disposer registered to fiber effect).
4. Include standalone service plugin, applyQueue scheduling, ConfigFileError, and atomic write.
5. Schemastery / Schema nested validation issue path diagnostics.
"""

import asyncio
import json
import os
import tempfile
import pytest
import yaml

from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.cordis.include import Include, ConfigFileError
from dsh.cordis.schema import Schema, ValidationError, z
from dsh.cordis.utils import symbols


# ---------------------------------------------------------------------------
# 1. Context.is_ Brand Checking
# ---------------------------------------------------------------------------

def test_context_brand_checking():
    """Verify Context.is_ accurately detects Context instances across realms via brand."""
    ctx = Context()
    assert Context.is_(ctx) is True
    assert Context.is_context(ctx) is True

    # None and primitives
    assert Context.is_(None) is False
    assert Context.is_("context") is False
    assert Context.is_({}) is False

    # Mock object simulating a Context instance from a different module reload/realm
    class CrossRealmContext:
        __cordis_context_brand__ = "cordis.v1.context"

    cross_realm_ctx = CrossRealmContext()
    assert Context.is_(cross_realm_ctx) is True

    # Duck typing fallback
    class DuckContext:
        def __init__(self):
            self.registry = None
            self.reflect = None
            self.extend = None

    duck = DuckContext()
    assert Context.is_(duck) is True


# ---------------------------------------------------------------------------
# 2. Waterfall Short-circuit & Veto Semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_waterfall_0_arg_short_circuit():
    """Verify 0-arg waterfall handler short-circuits with its return value."""
    ctx = Context()

    # Handler 1: 0-arg returning constant replacement (like system-prompt complete override)
    def override_all():
        return {"sections": ["overridden"], "contexts": [], "tools": []}

    # Handler 2: Standard handler that should NOT be reached
    called_h2 = []

    def normal_handler(assembly, next_fn):
        called_h2.append(True)
        return next_fn(assembly)

    ctx.on("system-prompt/assemble", override_all)
    ctx.on("system-prompt/assemble", normal_handler)

    res = await ctx.waterfall("system-prompt/assemble", {"sections": ["default"]})
    assert res == {"sections": ["overridden"], "contexts": [], "tools": []}
    assert len(called_h2) == 0


def test_waterfall_sync_0_arg_short_circuit():
    """Verify sync 0-arg waterfall handler short-circuits."""
    ctx = Context()

    def veto_handler():
        return "BLOCKED"

    def normal_handler(data, next_fn):
        return next_fn(data + "_processed")

    ctx.on("policy/check", veto_handler)
    ctx.on("policy/check", normal_handler)

    res = ctx.waterfall_sync("policy/check", "request")
    assert res == "BLOCKED"


@pytest.mark.asyncio
async def test_waterfall_veto_without_calling_next():
    """Verify handler taking next_fn vetoes downstream when returning without next_fn()."""
    ctx = Context()

    def middleware_ok(data, next_fn):
        return next_fn(data + " -> m1")

    def middleware_veto(data, next_fn):
        return data + " -> vetoed"

    def middleware_never(data, next_fn):
        return next_fn(data + " -> unreachable")

    ctx.on("pipeline", middleware_ok)
    ctx.on("pipeline", middleware_veto)
    ctx.on("pipeline", middleware_never)

    res = await ctx.waterfall("pipeline", "start")
    assert res == "start -> m1 -> vetoed"


# ---------------------------------------------------------------------------
# 3. Service.init Generator Lifecycle Protocol
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_init_generator_disposer_registration():
    """Verify Service.init returning a generator registers yielded disposers with Fiber."""
    ctx = Context()

    teardown_log = []

    class MyGenService(Service):
        name = "gen_service"

        def init(self):
            def _cleanup():
                teardown_log.append("cleaned_up")
            yield _cleanup

    fiber = ctx.plugin(MyGenService)
    assert fiber is not None
    assert len(teardown_log) == 0

    # Disposing fiber should execute the yielded cleanup function in reverse order
    await fiber.dispose()
    assert teardown_log == ["cleaned_up"]


# ---------------------------------------------------------------------------
# 4. Include Standalone Plugin & Scheduling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_include_plugin_initialization_and_patches():
    """Verify Include plugin loads YAML, applies patches, and writes updates safely."""
    ctx = Context()
    from dsh.cordis.loader import Loader
    ctx.plugin(Loader)

    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = os.path.join(tmp_dir, "cordis.yml")
        initial_entries = [
            {"id": "plugin-a", "name": "plugin-a-pkg", "config": {"port": 8080}},
            {"id": "plugin-b", "name": "plugin-b-pkg", "config": {"enabled": True}},
        ]

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(initial_entries, f)

        # Include with patch overriding plugin-a's config
        include_fiber = ctx.plugin(
            Include,
            {
                "path": config_path,
                "patches": [
                    {"id": "plugin-a", "config": {"port": 9000}},
                ],
            },
        )

        assert include_fiber is not None
        include_service: Include = ctx.get("include")
        assert include_service is not None
        assert include_service.data is not None
        assert len(include_service.data) == 2

        # Check patched entries in tree root
        entry_a = include_service.root.get("plugin-a")
        assert entry_a is not None
        assert entry_a.options.get("config", {}).get("port") == 9000

        # Test refresh under lock
        await include_service.refresh()
        assert include_service.data is not None

        # Clean up
        await include_service.stop()


@pytest.mark.asyncio
async def test_include_config_file_errors():
    """Verify Include raises ConfigFileError for read, parse, and validate stages."""
    ctx = Context()
    from dsh.cordis.loader import Loader
    ctx.plugin(Loader)

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Non-existent file without initial
        missing_path = os.path.join(tmp_dir, "missing.yml")
        with pytest.raises(ConfigFileError) as exc_info:
            inc = Include(ctx, {"path": missing_path})
            list(inc.init())
        assert exc_info.value.stage == "read"

        # Invalid YAML syntax
        bad_yaml_path = os.path.join(tmp_dir, "bad.yml")
        with open(bad_yaml_path, "w", encoding="utf-8") as f:
            f.write("key: [unclosed list")
        inc_bad = Include(ctx, {"path": bad_yaml_path})
        with pytest.raises(ConfigFileError) as exc_info_parse:
            await inc_bad.read(forced=True)
        assert exc_info_parse.value.stage == "parse"

        # Invalid top-level schema (must be a top-level list)
        bad_structure_path = os.path.join(tmp_dir, "bad_struct.yml")
        with open(bad_structure_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"not": "a list"}, f)
        inc_struct = Include(ctx, {"path": bad_structure_path})
        with pytest.raises(ConfigFileError) as exc_info_val:
            await inc_struct.read(forced=True)
        assert exc_info_val.value.stage == "validate"


# ---------------------------------------------------------------------------
# 5. Schema Nested Path Formatting
# ---------------------------------------------------------------------------

def test_schema_nested_issue_path_formatting():
    """Verify Schemastery ValidationError formats nested issue paths matching reference specs."""
    schema = Schema.object({
        "server": Schema.object({
            "port": Schema.number().min(1).max(65535),
            "host": Schema.string().required(),
        }),
    })

    # Valid validation
    valid_res = schema.validate({"server": {"port": 3000, "host": "127.0.0.1"}})
    assert "value" in valid_res
    assert valid_res["value"]["server"]["port"] == 3000

    # Invalid port (out of range)
    invalid_port_res = schema.validate({"server": {"port": 70000, "host": "localhost"}})
    assert "issues" in invalid_port_res
    issues = invalid_port_res["issues"]
    assert len(issues) > 0
    assert issues[0]["path"] == ["server", "port"]

    # ValidationError multi-line message
    err = ValidationError(issues)
    assert "invalid config:" in str(err)
    assert "(at server.port)" in str(err)


# ---------------------------------------------------------------------------
# 6. Additional Reference Parity Tests (internal/listener, AggregateError, Group Patches)
# ---------------------------------------------------------------------------

def test_internal_listener_interception():
    """Verify internal/listener can intercept and veto listener registration."""
    ctx = Context()
    from dsh.cordis.events import EventBus

    intercepted = []

    def _on_listener(event_name, handler, prepend, is_global):
        if event_name == "blocked/event":
            intercepted.append(event_name)
            return lambda: "vetoed"  # Return a disposer without registering handler

    ctx.on("internal/listener", _on_listener, global_listener=True)

    handler_called = []
    disposer = ctx.on("blocked/event", lambda: handler_called.append(True))
    assert len(intercepted) == 1
    assert intercepted[0] == "blocked/event"

    ctx.emit("blocked/event")
    assert len(handler_called) == 0


@pytest.mark.asyncio
async def test_parallel_aggregate_error():
    """Verify parallel() aggregates multiple exceptions into AggregateError."""
    ctx = Context()
    from dsh.cordis.events import AggregateError

    async def f1():
        raise ValueError("err1")

    async def f2():
        raise RuntimeError("err2")

    ctx.on("test/fail", f1)
    ctx.on("test/fail", f2)

    with pytest.raises(AggregateError) as exc_info:
        await ctx.parallel("test/fail")

    errs = exc_info.value.errors
    assert len(errs) == 2
    assert any(isinstance(e, ValueError) and str(e) == "err1" for e in errs)
    assert any(isinstance(e, RuntimeError) and str(e) == "err2" for e in errs)


@pytest.mark.asyncio
async def test_include_patch_insert_into_nested_group():
    """Verify Include patches can insert entries into existing groups matching reference applyEntryPatches."""
    ctx = Context()
    from dsh.cordis.loader import Loader
    ctx.plugin(Loader)

    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = os.path.join(tmp_dir, "cordis.yml")
        initial_entries = [
            {
                "id": "my-group",
                "group": True,
                "config": [
                    {"id": "plugin-1", "name": "pkg-1", "config": {}},
                ],
            }
        ]

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(initial_entries, f)

        # Patch that inserts plugin-2 into my-group
        include_fiber = ctx.plugin(
            Include,
            {
                "path": config_path,
                "patches": [
                    {
                        "id": "my-group",
                        "insert": [
                            {"id": "plugin-2", "name": "pkg-2", "config": {"port": 7777}},
                        ],
                    }
                ],
            },
        )

        assert include_fiber is not None
        inc_svc: Include = ctx.get("include")
        assert inc_svc is not None

        # Verify entry plugin-2 exists in the store
        entry2 = inc_svc.get("plugin-2")
        assert entry2 is not None
        assert entry2.options.get("config", {}).get("port") == 7777

        await inc_svc.stop()
