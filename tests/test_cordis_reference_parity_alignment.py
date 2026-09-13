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
import gc
import json
import os
import tempfile
import warnings
import pytest
import yaml

from dsh.boot.app_boot import settle_fibers
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import AggregateError, Loader
from dsh.cordis.service import Service
from dsh.cordis.include import Include, ConfigFileError
from dsh.cordis.schema import Schema, ValidationError, z
from dsh.cordis.utils import symbols


async def _settle_entry_plugin(ctx):
    """Entry plugin body used by the loader quiescence cases below."""
    await asyncio.sleep(0)


def _unawaited_loader_warnings():
    """Return 'never awaited' warnings GC reports for a loader coroutine."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    return [
        str(warning.message) for warning in caught
        if "never awaited" in str(warning.message) and "Entry" in str(warning.message)
    ]


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

    # Duck typing fallback rejected per G6-D1 (Context brand is sole arbiter)
    class DuckContext:
        def __init__(self):
            self.registry = None
            self.reflect = None
            self.extend = None

    duck = DuckContext()
    assert Context.is_(duck) is False


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

    async def middleware_ok(data, next_fn):
        res = await next_fn()
        return f"{res} (via m1)"

    def middleware_veto(data, next_fn):
        return data + " -> vetoed"

    def middleware_never(data, next_fn):
        return next_fn()

    ctx.on("pipeline", middleware_ok)
    ctx.on("pipeline", middleware_veto)
    ctx.on("pipeline", middleware_never)

    res = await ctx.waterfall("pipeline", "start")
    assert res == "start -> vetoed (via m1)"


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

    fiber = await ctx.plugin(MyGenService)
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
    await ctx.plugin(Loader)

    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = os.path.join(tmp_dir, "cordis.yml")
        initial_entries = [
            {"id": "plugin-a", "name": "plugin-a-pkg", "config": {"port": 8080}},
            {"id": "plugin-b", "name": "plugin-b-pkg", "config": {"enabled": True}},
        ]

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(initial_entries, f)

        # Include with patch overriding plugin-a's config
        # The probe entries name packages that are not installed; this case covers
        # the include service's tree and patch result, so only its own mount settles.
        include_fiber = ctx.plugin(
            Include,
            {
                "path": config_path,
                "patches": [
                    {"id": "plugin-a", "config": {"port": 9000}},
                ],
            },
        )

        await asyncio.sleep(0)
        assert include_fiber is not None
        # Root-context attribute access resolves a service the way the reference
        # proxy does for a runtime-less context (`reflect.get(name, false)`).
        include_service: Include = ctx.include
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

        # tree.ts settlement: the include tree owns the mount's apply and entry
        # tasks, and the probe entries name packages that are not installed, so
        # the apply rolls back and the mount fiber fails. Awaiting both leaves no
        # loader task running when the test's loop closes.
        await include_service.await_()
        with pytest.raises(AggregateError) as mount_error:
            await include_fiber.await_settled()
        assert "failed to import loader entry plugin-a" in str(mount_error.value)
        await asyncio.sleep(0)
        assert include_fiber.state == FiberState.FAILED
        assert include_service.get_tasks() == []

        # Clean up
        await include_service.stop()
        await include_service.flush_write()


@pytest.mark.asyncio
async def test_include_config_file_errors():
    """Verify Include raises ConfigFileError for read, parse, and validate stages."""
    ctx = Context()
    from dsh.cordis.loader import Loader
    await ctx.plugin(Loader)

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


@pytest.mark.asyncio
async def test_loader_tree_owns_entry_creation_and_initialization_tasks():
    """
    tree.ts `getTasks()`/`await()`: every entry creation and initialization task
    belongs to the tree, is reported while it is pending, and is awaited before
    settlement returns.
    """
    ctx = Context()
    ctx_loader_fiber = await ctx.plugin(Loader)
    loader = ctx.loader
    assert loader is not None
    loader.register_plugin_class("settle-pkg", _settle_entry_plugin)

    # The returned awaitable is intentionally dropped: the tree, not the caller,
    # owns the task it started.
    created = loader.create({"id": "settle-entry", "name": "settle-pkg", "config": {}})
    assert created is not None
    pending = loader.get_tasks()
    assert pending, "a freshly created entry reports its pending tree task"

    await loader.await_()
    await ctx_loader_fiber.await_settled()
    await asyncio.sleep(0)
    entry = loader.resolve("settle-entry")
    assert entry.fiber is not None
    assert entry.fiber.state == FiberState.ACTIVE
    assert loader.get_tasks() == []
    assert _unawaited_loader_warnings() == []


@pytest.mark.asyncio
async def test_loader_settlement_leaves_no_unawaited_entry_init_task():
    """
    An entry initialized through the loader is fully owned: after settlement no
    `Entry._init_task_runner` coroutine is left unawaited and no loader task is
    still pending on the loop.
    """
    ctx = Context()
    await ctx.plugin(Loader)
    loader = ctx.loader
    assert loader is not None
    loader.register_plugin_class("settle-pkg", _settle_entry_plugin)

    loader.load_from_dict([{"id": "dict-entry", "name": "settle-pkg", "config": {}}])
    await loader.await_()
    await asyncio.sleep(0)

    assert loader.get_tasks() == []
    assert _unawaited_loader_warnings() == []
    entry = loader.resolve("dict-entry")
    assert entry.fiber is not None
    assert entry.fiber.state == FiberState.ACTIVE


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
    await ctx.plugin(Loader)

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
        # The probe entries name packages that are not installed; this case covers
        # the include service's tree and patch result, so only its own mount settles.
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

        await asyncio.sleep(0)
        assert include_fiber is not None
        inc_svc: Include = ctx.include
        assert inc_svc is not None

        # Verify entry plugin-2 exists in the store
        entry2 = inc_svc.get("plugin-2")
        assert entry2 is not None
        assert entry2.options.get("config", {}).get("port") == 7777

        # tree.ts settlement: every apply and entry task the include tree started
        # is awaited before the mount's work is considered finished; the probe
        # entries cannot be imported, so the apply rolls back and the mount fails.
        await inc_svc.await_()
        with pytest.raises(AggregateError) as mount_error:
            await include_fiber.await_settled()
        assert "failed to import loader entry plugin-1" in str(mount_error.value)
        await asyncio.sleep(0)
        assert include_fiber.state == FiberState.FAILED
        assert inc_svc.get_tasks() == []

        await inc_svc.stop()
        await inc_svc.flush_write()


@pytest.mark.asyncio
async def test_settle_fibers_joins_the_root_fiber_teardown_with_its_dependent_inertia():
    """A root teardown owns no parent registration, so `settle_fibers` reports it.

    Reference: `fiber.ts` `dispose: () => Promise<void>` starts the teardown and
    `await()` joins the transition stored on the same fiber. Harness and CLI
    settlement then return only after a script bridge's dropped
    `void ctx.root.fiber.dispose()` finished, including the dependent fiber
    inertia its unload gathered.
    """
    ctx = Context()
    cleanup_started = asyncio.Event()
    release = asyncio.Event()
    log = []

    async def cleanup():
        cleanup_started.set()
        await release.wait()
        log.append("cleanup")

    ctx.effect(lambda: lambda: cleanup(), label="root-teardown")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settlement = ctx.fiber.schedule_settlement(ctx.fiber.dispose())
        joiner = asyncio.ensure_future(settle_fibers(ctx))
        await cleanup_started.wait()
        assert log == []
        assert not joiner.done()

        release.set()
        await joiner
        gc.collect()

    assert settlement.done()
    assert log == ["cleanup"]
    assert ctx.fiber.settlement_tasks() == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []
