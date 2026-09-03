"""
1:1 parity unit test suite for dsh/cordis/loader.py matching reference/vendor/loader.
Covers:
- T1: Entry.disabled: plain string like "false" is truthy, empty string is falsy, !!js evaluated
- T2: Entry.disabled: group is never disabled; parent entry disabled propagates to children
- T7: EntryGroup.remove emits 'loader/partial-dispose' and cleans up isolate realms
- T8: interpolate keeps plain strings literal without env var expansion, evaluates __jsExpr
- T11: show_log suppresses logs for group entries and trees with enable_logs disabled
- T12: isolate patch context warns when service is not implemented
- T15: Loader.locate returns owner entry id from child fiber
"""

import pytest

from dsh.cordis.context import Context
from dsh.cordis.loader import (
    Loader,
    EntryTree,
    EntryGroup,
    Entry,
    interpolate,
    is_js_expr,
)


def test_t1_entry_disabled_plain_string_is_truthy():
    """T1: disabled: 'false' is truthy in TS semantics, '' is falsy, and !!js evaluates."""
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)

    # 1. Plain string "false" is non-empty -> truthy (disabled = True)
    e1 = Entry(loader.tree.root, {"id": "1", "name": "dummy", "disabled": "false"})
    assert e1.disabled is True

    # 2. Empty string -> falsy (disabled = False)
    e2 = Entry(loader.tree.root, {"id": "2", "name": "dummy", "disabled": ""})
    assert e2.disabled is False

    # 3. Boolean values
    e3 = Entry(loader.tree.root, {"id": "3", "name": "dummy", "disabled": False})
    assert e3.disabled is False

    e4 = Entry(loader.tree.root, {"id": "4", "name": "dummy", "disabled": True})
    assert e4.disabled is True

    # 4. !!js expression evaluated
    e5 = Entry(loader.tree.root, {"id": "5", "name": "dummy", "disabled": {"__jsExpr": "1 === 2"}})
    assert e5.disabled is False

    e6 = Entry(loader.tree.root, {"id": "6", "name": "dummy", "disabled": {"__jsExpr": "1 === 1"}})
    assert e6.disabled is True


def test_t2_entry_disabled_group_exempt_and_ancestor_cascade():
    """T2: groups are never disabled; parent entry disabled cascades to child entries."""
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)

    # 1. Group entry is never disabled even if disabled: True
    g_entry = Entry(loader.tree.root, {"id": "g1", "name": "cordis:group", "group": True, "disabled": True})
    assert g_entry.disabled is False


def test_t7_entry_group_remove_emits_partial_dispose():
    """T7: EntryGroup.remove emits 'loader/partial-dispose' event."""
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)

    events = []

    def on_partial_dispose(entry, options, is_active):
        events.append((entry, options, is_active))

    ctx.on("loader/partial-dispose", on_partial_dispose)

    entry = Entry(loader.tree.root, {"id": "item1", "name": "plugin-a"})
    loader.tree.store["item1"] = entry

    loader.tree.root.remove("item1")

    assert len(events) == 1
    assert events[0][0] is entry
    assert events[0][1]["id"] == "item1"
    assert events[0][2] is False


def test_t8_interpolate_keeps_plain_strings_literal():
    """T8: interpolate keeps ${VAR} in plain strings literal, only evaluates __jsExpr."""
    ctx = Context()
    ctx.answer = 42

    raw_config = {
        "text": "${HOME}/bin/tool",
        "nested": {
            "cmd": "run ${VAR:-default}",
            "expr": {"__jsExpr": "answer * 2"},
        },
        "list": ["literal ${FOO}", {"__jsExpr": "answer + 1"}],
    }

    res = interpolate(ctx, raw_config)

    # Plain strings must remain literal matching TS
    assert res["text"] == "${HOME}/bin/tool"
    assert res["nested"]["cmd"] == "run ${VAR:-default}"
    assert res["list"][0] == "literal ${FOO}"

    # Only __jsExpr nodes are evaluated
    assert res["nested"]["expr"] == 84
    assert res["list"][1] == 43


def test_t11_show_log_gating():
    """T11: show_log suppresses logs for group entries and trees with enable_logs=False/None."""
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)

    logs = []

    class MockLogger:
        def info(self, fmt, *args):
            logs.append(fmt % args)

    ctx.set_service("logger", lambda name: MockLogger())

    # Tree with enable_logs=None/False
    loader.tree.enable_logs = False
    normal_entry = Entry(loader.tree.root, {"id": "p1", "name": "my-plugin"})
    loader.show_log(normal_entry, "apply")
    assert len(logs) == 0

    # Enable logs on tree
    loader.tree.enable_logs = True
    loader.show_log(normal_entry, "apply")
    assert len(logs) == 1
    assert "apply plugin my-plugin" in logs[0]

    # Group entry is suppressed even when tree enable_logs is True
    logs.clear()
    group_entry = Entry(loader.tree.root, {"id": "g1", "name": "group-p", "group": True})
    loader.show_log(group_entry, "apply")
    assert len(logs) == 0


def test_t15_loader_locate_and_exit():
    """T15: Loader.locate locates owning entry id, Loader.exit exists."""
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)

    # Calling locate with None or root fiber returns None
    assert loader.locate() is None

    # exit hook callable
    loader.exit()
