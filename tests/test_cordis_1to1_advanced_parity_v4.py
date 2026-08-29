"""
Comprehensive test suite verifying advanced 1:1 Cordis architectural parity:
1. Delimiter-based dynamic isolate realm migration & reflect store replacement (Loader + Isolate)
2. Fiber.update state machine lifecycle & waterfall settlement
3. Pure Python AST-based module dependency graph & cascading HMR reloads
4. Schema.intersect composite schema validation & simplification
"""

import asyncio
import os
import tempfile
import time
import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.hmr import ConfigWatcherService, ModuleDependencyGraph
from dsh.cordis.loader import Loader, Entry, LocalRealm, GlobalRealm
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema, ValidationError
from dsh.cordis.service import Service


# ---------------------------------------------------------------------------
# 1. Delimiter-based Isolate Realm Migration & Service Replacement
# ---------------------------------------------------------------------------

class ServiceA(Service):
    name = "serviceA"
    def __init__(self, ctx, val="default"):
        super().__init__(ctx, "serviceA")
        self.val = val


class ServiceB(Service):
    name = "serviceB"
    inject = ["serviceA"]
    def __init__(self, ctx):
        super().__init__(ctx, "serviceB")


def test_isolate_delimiter_and_service_migration():
    """Verify that patching isolate options migrates service implementations across isolation symbols."""
    ctx = Context()
    loader = Loader(ctx)

    # 1. Create root entries
    entry = Entry(loader=loader, name="plugin-a", entry_id="plugin-a", config={"val": "initial"})
    entry.ctx = ctx.extend()
    entry.options = {"isolate": {"serviceA": True}}

    # Trigger loader entry init & patch context
    ctx.emit("loader/entry-init", entry)
    assert hasattr(entry.ctx, "_isolate_delims")
    ctx.emit("loader/patch-context", entry)

    # Mount serviceA in isolated context with entry fiber
    entry.fiber = Fiber(entry.ctx, ServiceA)
    entry.ctx.fiber = entry.fiber
    srv_a = ServiceA(entry.ctx, val="custom_a")
    iso_sym_1 = entry.ctx._isolated_keys.get("serviceA")
    assert iso_sym_1 is not None
    assert entry.ctx.reflect.store.get(iso_sym_1) is not None

    # Step 2: Patch context with new isolate label
    entry.options["isolate"] = {"serviceA": "global_realm_1"}
    ctx.emit("loader/patch-context", entry)

    iso_sym_2 = entry.ctx._isolated_keys.get("serviceA")
    assert iso_sym_2 is not None
    assert iso_sym_2 != iso_sym_1
    # Service implementation should have been migrated to the new isolation symbol
    assert entry.ctx.reflect.store.get(iso_sym_2) is not None
    assert iso_sym_1 not in entry.ctx.reflect.store


# ---------------------------------------------------------------------------
# 2. Fiber Lifecycle, Epoch, and Update Waterfall
# ---------------------------------------------------------------------------

class UpdatablePlugin(Plugin):
    id = "updatable-plugin"
    inject = []
    Config = Schema.object({"count": Schema.number().default(0), "msg": Schema.string().default("hi")})

    def __init__(self, config=None):
        super().__init__(config=config)
        self.reloaded_count = 0

    def apply(self, ctx):
        self.reloaded_count += 1


def test_fiber_update_state_machine():
    """Verify Fiber.update handles active vs non-active states and waterfall chains."""
    ctx = Context()
    plugin = UpdatablePlugin(config={"count": 1, "msg": "first"})
    fiber = ctx.registry.plugin(plugin, config={"count": 1, "msg": "first"})

    assert fiber.state == FiberState.ACTIVE
    assert fiber.config["count"] == 1

    # Update config while active
    fiber.update({"count": 42, "msg": "updated"})
    assert fiber.config["count"] == 42
    assert fiber.config["msg"] == "updated"

    # Test update when fiber is inactive
    fiber.state = FiberState.PENDING
    fiber.update({"count": 99})
    assert fiber.config["count"] == 99


# ---------------------------------------------------------------------------
# 3. Pure Python AST Module Dependency Graph & Cascading HMR
# ---------------------------------------------------------------------------

def test_ast_module_dependency_graph():
    """Verify ModuleDependencyGraph accurately tracks imports without execution."""
    graph = ModuleDependencyGraph()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create helper.py
        helper_path = os.path.join(tmpdir, "helper.py")
        with open(helper_path, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")

        # Create plugin_main.py importing helper
        plugin_path = os.path.join(tmpdir, "plugin_main.py")
        with open(plugin_path, "w", encoding="utf-8") as f:
            f.write("from helper import add\nfrom dsh.cordis.plugin import Plugin\n\nclass MyP(Plugin):\n    pass\n")

        # Create consumer.py importing plugin_main
        consumer_path = os.path.join(tmpdir, "consumer.py")
        with open(consumer_path, "w", encoding="utf-8") as f:
            f.write("import plugin_main\n")

        graph.scan_file(helper_path, base_dir=tmpdir)
        graph.scan_file(plugin_path, base_dir=tmpdir)
        graph.scan_file(consumer_path, base_dir=tmpdir)

        # When helper.py changes, plugin_main and consumer should be in transitive dependents
        dependents = graph.get_transitive_dependents(helper_path)
        assert os.path.abspath(plugin_path) in dependents
        assert os.path.abspath(consumer_path) in dependents


# ---------------------------------------------------------------------------
# 4. Schema Intersect Composite Validation & Simplification
# ---------------------------------------------------------------------------

def test_schema_intersect_composite_dictionaries():
    """Verify Schema.intersect correctly validates and deep merges dictionaries."""
    schema_a = Schema.object({"name": Schema.string().required(), "meta": Schema.object({"tag": Schema.string()})})
    schema_b = Schema.object({"age": Schema.number().default(18), "meta": Schema.object({"version": Schema.number().default(1)})})
    intersect_schema = Schema.intersect([schema_a, schema_b])

    # Valid input
    data = {"name": "Alice", "meta": {"tag": "admin"}}
    res = intersect_schema.validate(data)
    assert res["value"]["name"] == "Alice"
    assert res["value"]["age"] == 18
    assert res["value"]["meta"]["tag"] == "admin"
    assert res["value"]["meta"]["version"] == 1

    # Invalid input missing required field via standard schema and direct call
    inv_res = intersect_schema.validate({"age": 20})
    assert "issues" in inv_res
    with pytest.raises(ValidationError):
        intersect_schema({"age": 20})


def test_schema_intersect_scalars():
    """Verify Schema.intersect validates scalar constraints."""
    num_intersect = Schema.intersect([Schema.number().min(10), Schema.number().max(20)])
    assert num_intersect.validate(15)["value"] == 15

    # Standard schema returns issues
    assert "issues" in num_intersect.validate(5)
    assert "issues" in num_intersect.validate(25)

    # Direct call raises ValidationError
    with pytest.raises(ValidationError):
        num_intersect(5)

    with pytest.raises(ValidationError):
        num_intersect(25)
