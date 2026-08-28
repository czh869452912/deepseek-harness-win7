"""
Unit tests verifying 1:1 Cordis Core Architecture Parity
Tests DisposableList, Composite Epochs & Cascade Reloading, LoggerService, EntryTree, and Event Interception.
"""

import asyncio
import pytest

from dsh.cordis.context import Context
from dsh.cordis.events import AggregateError, is_bailed
from dsh.cordis.fiber import Fiber, FiberState, INACTIVE_EPOCH
from dsh.cordis.logger import Exporter, Logger, LoggerLevel, LoggerService, Message
from dsh.cordis.loader import Entry, EntryGroup, EntryTree, Loader
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.utils import DisposableList, symbols


def test_disposable_list_operations():
    dlist = DisposableList()
    logs = []

    d1 = lambda: logs.append("d1")
    d2 = lambda: logs.append("d2")
    d3 = lambda: logs.append("d3")

    rm1 = dlist.push(d1)
    rm2 = dlist.push(d2)
    rm3 = dlist.push(d3)

    assert len(dlist) == 3

    # Test O(1) removal by returned disposer
    assert rm2() is True
    assert len(dlist) == 2
    assert dlist.delete(d1) is True
    assert len(dlist) == 1

    # Test clear in reverse order
    remaining = dlist.clear()
    assert len(remaining) == 1
    assert remaining[0] is d3
    assert len(dlist) == 0


def test_logger_service_and_color_formatting():
    ctx = Context()
    assert hasattr(ctx, "logger")
    assert isinstance(ctx.logger, LoggerService)

    received_messages = []

    def custom_export(msg: Message):
        received_messages.append(msg)

    # Register custom exporter
    disposer = ctx.logger.exporter(Exporter(export_fn=custom_export, colors=3))

    named_log = ctx.logger("test-subsystem")
    named_log.info("Hello %s from %C, code: %d", "world", 42)

    assert len(received_messages) == 1
    msg = received_messages[0]
    assert msg.name == "test-subsystem"
    assert msg.level == LoggerLevel.INFO
    assert msg.args == ["Hello %s from %C, code: %d", "world", 42]

    # Test formatted text output
    exporter = Exporter(colors=3)
    formatted = Logger.format(exporter, msg)
    assert "Hello world from" in formatted
    assert "42" in formatted

    # Test memory ring buffer
    assert len(ctx.logger.buffer) >= 1
    assert ctx.logger.buffer[-1].name == "test-subsystem"

    disposer()


def test_composite_epoch_and_cascade_reloading():
    ctx = Context()

    class DatabasePlugin1(Plugin):
        id = "db1"
        def apply(self, c):
            c.set_service("database", {"version": 1})

    class DatabasePlugin2(Plugin):
        id = "db2"
        def apply(self, c):
            c.set_service("database", {"version": 2})

    class DownstreamPlugin(Plugin):
        name = "downstream"
        inject = ["database"]

        def __init__(self, config=None):
            super().__init__(config)
            self.reload_count = 0

        def apply(self, c):
            self.reload_count += 1
            db = c.get("database")
            c.set_service("downstream_val", f"ready_v{db['version']}")

    # 1. Mount downstream plugin (should be PENDING because database is not yet provided)
    downstream_fiber = ctx.registry.plugin(DownstreamPlugin)
    assert downstream_fiber.state == FiberState.PENDING
    assert not ctx.has("downstream_val")

    # 2. Provide database via db1 plugin -> Downstream should activate
    f_db1 = ctx.registry.plugin(DatabasePlugin1)
    assert downstream_fiber.state == FiberState.ACTIVE
    assert ctx.get("downstream_val") == "ready_v1"
    assert downstream_fiber.plugin.reload_count == 1
    epoch_db1 = downstream_fiber.epoch
    assert epoch_db1 == f":{f_db1.uid}"

    # 3. Unload db1 -> Downstream should transition to PENDING
    ctx.unload_plugin("db1")
    assert downstream_fiber.state == FiberState.PENDING
    assert downstream_fiber.epoch == INACTIVE_EPOCH

    # 4. Load db2 -> Downstream should automatically reload with new provider fiber UID
    f_db2 = ctx.registry.plugin(DatabasePlugin2)
    assert downstream_fiber.state == FiberState.ACTIVE
    assert ctx.get("downstream_val") == "ready_v2"
    assert downstream_fiber.plugin.reload_count == 2
    assert downstream_fiber.epoch == f":{f_db2.uid}"


def test_dynamic_service_check_predicate():
    ctx = Context()
    is_ready = False

    class GateService(Service):
        provide_name = "gate"
        def __init__(self, ctx, name=None):
            super().__init__(ctx, name=name)

        def _check_availability(self):
            return is_ready

    class ConsumerPlugin(Plugin):
        name = "consumer"
        inject = ["gate"]
        def apply(self, c):
            c.set_service("consumer_ready", True)

    gate = GateService(ctx)
    consumer_fiber = ctx.registry.plugin(ConsumerPlugin)

    # Initial check: is_ready is False -> PENDING
    assert consumer_fiber.state == FiberState.PENDING
    assert not ctx.has("consumer_ready")

    # Change predicate to True and notify
    is_ready = True
    ctx.reflect.notify(["gate"])
    assert consumer_fiber.state == FiberState.ACTIVE
    assert ctx.get("consumer_ready") is True


def test_entry_tree_hierarchy_and_rollback():
    ctx = Context()
    loader = Loader(ctx)

    class SamplePlugin(Plugin):
        name = "sample"
        def apply(self, c):
            c.set_service("sample_ok", True)

    loader.register_plugin_class("sample_plugin", SamplePlugin)

    tree = EntryTree(ctx)
    eid = tree.create({"name": "sample_plugin", "config": {"key": "val"}})
    assert eid in tree.store
    entry = tree.resolve(eid)
    assert entry.name == "sample_plugin"

    # Test update and removal
    tree.update(eid, {"config": {"key": "updated"}})
    assert tree.store[eid].config == {"key": "updated"}

    tree.remove(eid)
    assert eid not in tree.store


def test_internal_listener_interception():
    ctx = Context()
    intercepted_events = []

    # Register an internal/listener interceptor
    def intercept_listener(event_name, handler, prepend):
        intercepted_events.append(event_name)
        return None

    ctx.on("internal/listener", intercept_listener)

    # Register a standard event
    ctx.on("custom/action", lambda: "action_res")
    assert "custom/action" in intercepted_events
