"""
Unit tests for Cordis Realm isolation and loader patch-context matching reference/vendor/loader/src/config/isolate.ts.
"""

import pytest
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader, Entry, LocalRealm, GlobalRealm
from dsh.cordis.service import Service


class DummyDbService(Service):
    name = "db"
    def __init__(self, ctx: Context, url: str = "sqlite://"):
        super().__init__(ctx, "db")
        self.url = url


def test_local_and_global_realms():
    """Verify LocalRealm and GlobalRealm symbol generation."""
    entry = Entry(loader=None, name="test-entry", entry_id="abc1234")
    local_realm = LocalRealm(entry)
    assert local_realm.suffix == "#abc1234"
    assert local_realm.access("db", create=True) == "db#abc1234"
    assert local_realm.access("db", create=False) == "db#abc1234"
    assert local_realm.size == 1

    local_realm.delete("db")
    assert local_realm.size == 0

    global_realm = GlobalRealm("shared-cluster")
    assert global_realm.suffix == "@shared-cluster"
    assert global_realm.access("cache", create=True) == "cache@shared-cluster"
    assert global_realm.size == 1


def test_loader_patch_context_local_isolation():
    """Verify that loader/patch-context isolates services locally when isolate: { db: true }."""
    ctx = Context()
    loader = Loader(ctx)

    root_db = DummyDbService(ctx, url="sqlite://root")

    entry = Entry(loader=loader, name="isolated-entry", entry_id="iso1")
    entry.options["isolate"] = {"db": True}

    # Emit patch context
    called = []
    ctx.emit("loader/patch-context", entry, lambda: called.append(True))
    assert called == [True]

    assert "db" in entry.ctx._isolated_keys
    assert entry.ctx._isolated_keys["db"] == "db#iso1"

    # In isolated context, root db is hidden
    assert entry.ctx.get_service("db") is None


def test_loader_patch_context_global_shared_realm():
    """Verify that two entries with the same isolate label share the isolated realm."""
    ctx = Context()
    loader = Loader(ctx)

    entry1 = Entry(loader=loader, name="plugin-1", entry_id="e1")
    entry1.options["isolate"] = {"cache": "redis-cluster"}

    entry2 = Entry(loader=loader, name="plugin-2", entry_id="e2")
    entry2.options["isolate"] = {"cache": "redis-cluster"}

    ctx.emit("loader/patch-context", entry1, lambda: None)
    ctx.emit("loader/patch-context", entry2, lambda: None)

    assert entry1.ctx._isolated_keys["cache"] == "cache@redis-cluster"
    assert entry2.ctx._isolated_keys["cache"] == "cache@redis-cluster"
    assert entry1.ctx._isolated_keys["cache"] == entry2.ctx._isolated_keys["cache"]


def test_loader_partial_dispose_realm_gc():
    """Verify that GlobalRealm is garbage collected when no entries reference it."""
    ctx = Context()
    loader = Loader(ctx)

    entry1 = Entry(loader=loader, name="plugin-1", entry_id="e1")
    entry1.options["isolate"] = {"mq": "rabbit-mq"}
    ctx.emit("loader/patch-context", entry1, lambda: None)

    assert "rabbit-mq" in loader._realms
    assert loader._realms["rabbit-mq"].size == 1

    # Dispose entry1
    ctx.emit("loader/partial-dispose", entry1, {"isolate": {"mq": "rabbit-mq"}}, False)
    assert "rabbit-mq" not in loader._realms
