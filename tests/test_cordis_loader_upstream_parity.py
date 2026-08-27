import asyncio
import copy
import os
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader, evaluate, interpolate
from dsh.cordis.loader_group import EntryGroup, LoaderAggregateError


class RecordingLoader(Loader):
    def __init__(self, ctx):
        self.writes = []
        super().__init__(ctx)

    def write(self):
        self.writes.append(copy.deepcopy(self.root.data))


def plugin(apply, inject=None):
    dependencies = inject or []

    class TestPlugin:
        name = "loader-test-plugin"
        inject = dependencies

        def apply(self, ctx, config):
            return apply(ctx, config)

    return TestPlugin


def test_unknown_plugin_fails_loudly():
    loader = Loader(Context())

    with pytest.raises(ImportError, match="unknown-loader-plugin"):
        loader.load_from_dict([{"id": "missing", "name": "unknown-loader-plugin"}])


@pytest.mark.asyncio
async def test_entry_group_update_rolls_back_new_entries_on_failure():
    ctx = Context()
    loader = Loader(ctx)
    active = []

    async def good_apply(_ctx, config):
        active.append(config["value"])

        def dispose():
            active.remove(config["value"])

        return dispose

    def bad_apply(_ctx, _config):
        raise RuntimeError("apply exploded")

    loader.register_plugin_class("good", plugin(good_apply))
    loader.register_plugin_class("bad", plugin(bad_apply))
    original = [{"id": "good", "name": "good", "config": {"value": "old"}}]
    await loader.root.update(original)

    with pytest.raises(RuntimeError, match="failed to apply loader entry bad"):
        await loader.root.update([
            {"id": "good", "name": "good", "config": {"value": "new"}},
            {"id": "bad", "name": "bad"},
        ])

    assert loader.root.data == original
    assert list(loader.store) == ["good"]
    assert active == ["old"]


@pytest.mark.asyncio
async def test_tree_create_update_move_remove_and_persistence_seam():
    loader = RecordingLoader(Context())
    seen = []

    loader.register_plugin_class("leaf", plugin(lambda _ctx, config: seen.append(config["value"])))
    loader.register_plugin_class("other", plugin(lambda _ctx, config: seen.append(config["value"])))

    entry_id = await loader.create({"name": "leaf", "config": {"value": 1}})
    assert loader.resolve(entry_id).options["name"] == "leaf"
    await loader.update(entry_id, {"name": "other", "config": {"value": 2}})
    assert loader.resolve(entry_id).options["name"] == "other"
    await loader.remove(entry_id)

    with pytest.raises(RuntimeError, match="cannot resolve entry"):
        loader.resolve(entry_id)
    assert len(loader.writes) == 3


@pytest.mark.asyncio
async def test_group_nested_resolution_and_builtin_import():
    loader = Loader(Context())
    calls = []
    loader.register_plugin_class("leaf", plugin(lambda _ctx, config: calls.append(config["value"])))

    await loader.root.update([{
        "id": "group",
        "name": "cordis:group",
        "group": True,
        "config": [{"id": "child", "name": "leaf", "config": {"value": 1}}],
    }])
    await loader.wait()

    assert loader.import_plugin("cordis:group") is loader.builtins["group"]
    assert loader.resolve("group:child").parent is loader.resolve("group").subgroup
    assert calls == [1]


@pytest.mark.asyncio
async def test_js_nodes_interpolate_per_entry_without_mutating_persisted_options(monkeypatch):
    monkeypatch.setenv("LOADER_PARITY_VALUE", "from-env")
    loader = Loader(Context())
    received = []
    loader.register_plugin_class("capture", plugin(lambda _ctx, config: received.append(config)))

    await loader.root.update([{
        "id": "capture",
        "name": "capture",
        "config": {
            "value": {"__jsExpr": "process.env.LOADER_PARITY_VALUE ?? 'fallback'"},
            "windows": {"__jsExpr": "process.platform === 'win32'"},
        },
    }])

    assert received == [{"value": "from-env", "windows": os.name == "nt"}]
    assert loader.resolve("capture").options["config"]["value"] == {
        "__jsExpr": "process.env.LOADER_PARITY_VALUE ?? 'fallback'",
    }


@pytest.mark.asyncio
async def test_inject_rows_activate_independently_of_config_order():
    ctx = Context()
    loader = Loader(ctx)
    calls = []

    consumer = plugin(lambda plugin_ctx, _config: calls.append(plugin_ctx.get("gate")))

    def provide(plugin_ctx, _config):
        return plugin_ctx.provide("gate", "ready")

    loader.register_plugin_class("consumer", consumer)
    loader.register_plugin_class("provider", plugin(provide))
    await loader.root.update([
        {"id": "consumer", "name": "consumer", "inject": ["gate"]},
        {"id": "provider", "name": "provider"},
    ])
    await loader.wait()

    assert calls == ["ready"]


@pytest.mark.asyncio
async def test_isolate_realms_are_local_or_shared_by_label():
    loader = Loader(Context())
    loader.register_plugin_class("noop", plugin(lambda _ctx, _config: None))
    await loader.root.update([
        {"id": "one", "name": "noop", "isolate": {"db": "shared"}},
        {"id": "two", "name": "noop", "isolate": {"db": "shared"}},
        {"id": "local", "name": "noop", "isolate": {"db": True}},
    ])

    one = loader.resolve("one").ctx._isolated_keys["db"]
    two = loader.resolve("two").ctx._isolated_keys["db"]
    local = loader.resolve("local").ctx._isolated_keys["db"]
    assert one is two
    assert local is not one


@pytest.mark.asyncio
async def test_loader_wait_observes_delayed_entry_and_remove_disposes_owned_effects():
    loader = Loader(Context())
    lifecycle = []

    async def delayed(_ctx, _config):
        await asyncio.sleep(0.01)
        lifecycle.append("started")
        return lambda: lifecycle.append("disposed")

    loader.register_plugin_class("delayed", plugin(delayed))
    await loader.root.update([{"id": "delayed", "name": "delayed"}])
    await loader.wait()
    await loader.remove("delayed")

    assert lifecycle == ["started", "disposed"]


@pytest.mark.asyncio
async def test_entry_fiber_update_persists_runtime_config():
    loader = RecordingLoader(Context())
    configs = []
    loader.register_plugin_class("capture", plugin(lambda _ctx, config: configs.append(config)))
    await loader.root.update([{
        "id": "capture", "name": "capture", "config": {"value": 1},
    }])
    entry = loader.resolve("capture")

    update = entry.fiber.update({"value": 2})
    if asyncio.iscoroutine(update):
        await update
    await entry.fiber

    assert entry.options["config"] == {"value": 2}
    assert loader.writes[-1][0]["config"] == {"value": 2}
    assert configs[-1] == {"value": 2}


@pytest.mark.asyncio
async def test_entry_self_dispose_is_persisted_as_disabled():
    loader = RecordingLoader(Context())
    loader.register_plugin_class("noop", plugin(lambda _ctx, _config: None))
    await loader.root.update([{"id": "noop", "name": "noop"}])
    entry = loader.resolve("noop")

    await entry.fiber.dispose()

    assert entry.options["disabled"] is True
    assert loader.writes[-1][0]["disabled"] is True


def test_yaml_js_tag_and_relative_python_module_import(tmp_path, monkeypatch):
    monkeypatch.setenv("LOADER_YAML_VALUE", "yaml-value")
    module = tmp_path / "sample_plugin.py"
    module.write_text(
        "def apply(ctx, config):\n"
        "    ctx.root.loader_yaml_value = config['value']\n",
        encoding="utf-8",
    )
    preset = tmp_path / "preset.yaml"
    preset.write_text(
        "- id: sample\n"
        "  name: ./sample_plugin.py\n"
        "  config:\n"
        "    value: !!js process.env.LOADER_YAML_VALUE ?? 'fallback'\n",
        encoding="utf-8",
    )
    ctx = Context()
    loader = Loader(ctx, {"baseUrl": str(tmp_path)})

    loader.load_preset_file(str(preset))

    assert ctx.loader_yaml_value == "yaml-value"
    assert loader.resolve("sample").options["config"]["value"] == {
        "__jsExpr": "process.env.LOADER_YAML_VALUE ?? 'fallback'",
    }


@pytest.mark.asyncio
async def test_entry_update_commits_into_persisted_options_object_across_move():
    loader = RecordingLoader(Context())
    loader.register_plugin_class("leaf", plugin(lambda _ctx, _config: None))
    await loader.root.update([
        {"id": "leaf", "name": "leaf", "config": {"value": 1}},
        {"id": "group", "name": "cordis:group", "group": True, "config": []},
    ])
    entry = loader.resolve("leaf")
    persisted = loader.root.data[0]

    await loader.update("leaf", {"config": {"value": 2}})
    assert entry.options is persisted
    assert persisted["config"] == {"value": 2}

    await loader.update("leaf", {"disabled": True})
    await loader.update("leaf", {"disabled": None})
    assert entry.options is persisted
    assert "disabled" not in persisted

    await loader.update("leaf", {}, parent="group")
    assert entry.options is persisted
    assert persisted not in loader.root.data
    assert loader.resolve("group").subgroup.data == [persisted]


@pytest.mark.asyncio
async def test_loader_await_intercept_keeps_consumer_pending_until_entries_settle():
    ctx = Context()
    loader = Loader(ctx)
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed(_ctx, _config):
        started.set()
        await release.wait()

    loader.register_plugin_class("delayed", plugin(delayed))
    loading = asyncio.create_task(loader.root.update([
        {"id": "delayed", "name": "delayed"},
    ]))
    await started.wait()
    calls = []
    consumer = ctx.registry.inject(
        {"loader": {"await": True}},
        lambda _child: calls.append("active"),
    )
    await asyncio.sleep(0)

    assert consumer.state == FiberState.PENDING
    assert calls == []

    release.set()
    await loading
    await consumer
    assert calls == ["active"]


@pytest.mark.asyncio
async def test_move_reparents_entry_base_url_before_expression_update():
    loader = Loader(Context(), {"baseUrl": "root-base"})
    seen = []
    loader.register_plugin_class("capture", plugin(lambda ctx, config: seen.append(
        (config["base"], getattr(ctx._parent, "baseUrl", None))
    )))
    await loader.root.update([
        {
            "id": "leaf",
            "name": "capture",
            "config": {"base": {"__jsExpr": "baseUrl"}},
        },
        {"id": "group", "name": "cordis:group", "group": True, "config": []},
    ])
    group = loader.resolve("group").subgroup
    group.ctx.baseUrl = "nested-base"

    await loader.update(
        "leaf",
        {},
        parent="group",
    )
    await loader.update("leaf", {"config": {
        "base": {"__jsExpr": "baseUrl"},
        "revision": 2,
    }})

    entry = loader.resolve("leaf")
    assert entry.ctx._parent is group.ctx
    assert entry.ctx.baseUrl == "nested-base"
    assert seen[-1] == ("nested-base", "nested-base")


@pytest.mark.asyncio
async def test_isolate_only_update_transfers_provider_without_restart_and_notifies_scopes():
    loader = Loader(Context())
    loads = []
    consumers = []

    def provide_db(ctx, _config):
        service = object()
        loads.append(service)
        ctx.provide("db", service)

    def consume_old(ctx, _config):
        consumers.append(("old-load", ctx.db))
        return lambda: consumers.append(("old-unload", ctx.db))

    def consume_new(ctx, _config):
        consumers.append(("new-load", ctx.db))

    loader.register_plugin_class("provider", plugin(provide_db))
    loader.register_plugin_class("old", plugin(consume_old, ["db"]))
    loader.register_plugin_class("new", plugin(consume_new, ["db"]))
    await loader.root.update([
        {"id": "provider", "name": "provider", "isolate": {"db": "old"}},
        {"id": "old", "name": "old", "isolate": {"db": "old"}},
        {"id": "new", "name": "new", "isolate": {"db": "new"}},
    ])
    provider = loader.resolve("provider")
    impl = provider.fiber.store["db"]
    assert consumers == [("old-load", loads[0])]

    await loader.update("provider", {"isolate": {"db": "new"}})
    await loader.wait()

    assert loads == [loads[0]]
    assert provider.fiber.store["db"] is impl
    assert consumers[0] == ("old-load", loads[0])
    assert set(consumers[1:]) == {
        ("old-unload", loads[0]),
        ("new-load", loads[0]),
    }


@pytest.mark.asyncio
async def test_registry_delete_does_not_persist_loader_entry_as_disabled():
    loader = RecordingLoader(Context())
    loader.register_plugin_class("noop", plugin(lambda _ctx, _config: None))
    await loader.root.update([{"id": "noop", "name": "noop"}])
    entry = loader.resolve("noop")
    callback = entry.fiber.runtime.callback

    loader.ctx.registry.delete(callback)
    await entry.fiber.dispose()

    assert entry.fiber.uid is None
    assert "disabled" not in entry.options
    assert not loader.writes


@pytest.mark.asyncio
async def test_entry_rollback_error_preserves_apply_and_rollback_failures():
    loader = Loader(Context())
    old_loads = []

    def old_apply(_ctx, _config):
        old_loads.append("load")
        if len(old_loads) > 1:
            raise RuntimeError("rollback apply failed")

    def new_apply(_ctx, _config):
        raise RuntimeError("new apply failed")

    loader.register_plugin_class("old", plugin(old_apply))
    loader.register_plugin_class("new", plugin(new_apply))
    await loader.root.update([{"id": "entry", "name": "old"}])

    with pytest.raises(RuntimeError, match="failed to rollback") as caught:
        await loader.update("entry", {"name": "new"})

    cause = caught.value.__cause__
    assert isinstance(cause, LoaderAggregateError)
    assert [str(error) for error in cause.errors] == [
        "new apply failed",
        "rollback apply failed",
    ]


@pytest.mark.asyncio
async def test_group_update_stops_after_owner_disposal_without_rollback():
    ctx = Context()
    loader = Loader(ctx)
    owner = ctx.registry.plugin(lambda _ctx, _config: None)
    await owner
    gate = asyncio.Event()

    class FailingAfterDisposeGroup(EntryGroup):
        async def create(self, options):
            await gate.wait()
            raise RuntimeError("late failure")

    group = FailingAfterDisposeGroup(owner.ctx, loader)
    update = asyncio.create_task(group.update([{"id": "late", "name": "unused"}]))
    await asyncio.sleep(0)
    await owner.dispose()
    gate.set()

    await update
    assert group.data == []


@pytest.mark.asyncio
async def test_nested_group_data_is_owner_config_and_persists_child_mutations():
    loader = RecordingLoader(Context())
    loader.register_plugin_class("leaf", plugin(lambda _ctx, _config: None))
    await loader.root.update([
        {"id": "group", "name": "cordis:group", "group": True, "config": []},
        {"id": "moving", "name": "leaf"},
    ])
    group_entry = loader.resolve("group")
    group = group_entry.subgroup

    assert group.data is group_entry.options["config"]

    child_id = await loader.create({"name": "leaf"}, parent="group")
    child_local_id = child_id.rsplit(":", 1)[-1]
    assert group.data is group_entry.options["config"]
    assert [row["id"] for row in loader.writes[-1][0]["config"]] == [child_local_id]

    await loader.update("moving", {}, parent="group")
    assert group.data is group_entry.options["config"]
    assert [row["id"] for row in loader.writes[-1][0]["config"]] == [
        child_local_id,
        "moving",
    ]

    await loader.remove(child_id)
    assert group.data is group_entry.options["config"]
    assert [row["id"] for row in loader.writes[-1][0]["config"]] == ["moving"]


@pytest.mark.asyncio
async def test_runtime_update_persists_only_after_restart_succeeds():
    loader = RecordingLoader(Context())

    def apply(_ctx, config):
        if config.get("fail"):
            raise RuntimeError("restart rejected")

    loader.register_plugin_class("fallible", plugin(apply))
    await loader.root.update([
        {"id": "fallible", "name": "fallible", "config": {"fail": False}},
    ])
    entry = loader.resolve("fallible")

    update = entry.fiber.update({"fail": True})
    with pytest.raises(RuntimeError, match="restart rejected"):
        if asyncio.iscoroutine(update):
            await update
        await entry.fiber

    assert entry.options["config"] == {"fail": False}
    assert loader.writes == []


def test_shipped_bundle_expression_matrix(monkeypatch, tmp_path):
    monkeypatch.delenv("DSH_TOOLS_MODE", raising=False)
    monkeypatch.delenv("DSH_TELEMETRY_MODE", raising=False)
    monkeypatch.setenv("DSH_PERMISSION_MODE", "danger-full-access")
    ctx = Context()
    ctx.webStartup = SimpleNamespace(
        host=None,
        port=4123,
        openBrowser=False,
        trustedHosts=["startup.local"],
    )
    ctx.webRuntime = SimpleNamespace(trustedHosts=["runtime.local"])
    ctx.headlessStartup = SimpleNamespace(task="build")
    ctx.dshHomePath = lambda name: os.path.join(str(tmp_path), name)
    ctx.provide("answer", 42)

    matrix = {
        "process.env.DSH_TOOLS_MODE": None,
        "process.env.DSH_TELEMETRY_MODE || 'DISABLED'": "DISABLED",
        "process.env.DSH_PERMISSION_MODE ?? 'workspace-write'": "danger-full-access",
        "process.platform === 'win32'": os.name == "nt",
        "process.platform !== 'win32'": os.name != "nt",
        "process.cwd()": os.getcwd(),
        "ctx.webStartup.host ?? '127.0.0.1'": "127.0.0.1",
        "ctx.webStartup.port ?? 3080": 4123,
        "ctx.webStartup.openBrowser": False,
        "ctx.webStartup.trustedHosts": ["startup.local"],
        "ctx.webRuntime.trustedHosts": ["runtime.local"],
        "ctx.headlessStartup.task": "build",
        "ctx.get('answer')": 42,
        "dshHomePath('sessions')": os.path.join(str(tmp_path), "sessions"),
        "!ctx.webStartup.openBrowser": True,
        "ctx.webStartup.port === 4123 && 'ready'": "ready",
        "(process.env.DSH_PERMISSION_MODE ?? 'workspace-write') === "
        "'danger-full-access' ? 'never' : 'ask'": "never",
    }
    assert {source: evaluate(ctx, source) for source in matrix} == matrix
    assert interpolate(ctx, {
        "items": [
            {"__jsExpr": "ctx.webStartup.port ?? 3080"},
            {"nested": {"__jsExpr": "dshHomePath('storages')"}},
        ],
    }) == {
        "items": [
            4123,
            {"nested": os.path.join(str(tmp_path), "storages")},
        ],
    }
    with pytest.raises(ValueError, match="unsupported loader"):
        evaluate(ctx, "JSON.parse('unsafe')")


@pytest.mark.asyncio
async def test_expression_resolves_after_injected_provider_activation():
    loader = Loader(Context())
    received = []

    loader.register_plugin_class(
        "consumer",
        plugin(lambda _ctx, config: received.append(config["value"]), ["answer"]),
    )

    def provide_answer(ctx, _config):
        ctx.provide("answer", 42)

    loader.register_plugin_class("provider", plugin(provide_answer))
    await loader.root.update([
        {
            "id": "consumer",
            "name": "consumer",
            "config": {"value": {"__jsExpr": "ctx.get('answer')"}},
        },
        {"id": "provider", "name": "provider"},
    ])
    await loader.wait()

    assert received == [42]


@pytest.mark.asyncio
async def test_tree_wait_notifies_loader_after_update_tasks_settle():
    ctx = Context()
    loader = Loader(ctx)
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed(_ctx, config):
        if config.get("wait"):
            started.set()
            await release.wait()

    loader.register_plugin_class("delayed", plugin(delayed))
    await loader.root.update([
        {"id": "delayed", "name": "delayed", "config": {"wait": False}},
    ])
    entry = loader.resolve("delayed")
    update_result = entry.fiber.update({"wait": True})
    updating = asyncio.ensure_future(update_result)
    await started.wait()

    calls = []
    consumer = ctx.registry.inject(
        {"loader": {"await": True}},
        lambda _child: calls.append("active"),
    )
    assert consumer.state == FiberState.PENDING
    waiting = asyncio.create_task(loader.wait())

    release.set()
    await updating
    await waiting
    await asyncio.sleep(0)

    assert calls == ["active"]
    assert consumer.state == FiberState.ACTIVE


@pytest.mark.asyncio
async def test_internal_plugin_associates_active_child_before_uid_guard():
    ctx = Context()
    ctx.provide("gate", "ready")
    loader = Loader(ctx)
    children = []
    parent_contexts = []
    publications = []

    def observe_plugin(fiber):
        if parent_contexts and fiber.parent is parent_contexts[-1]:
            publications.append((
                fiber,
                fiber.uid,
                fiber.state,
                fiber.parent,
                getattr(fiber, "entry", None),
                dict(fiber.inject),
            ))

    ctx.on("internal/plugin", observe_plugin, global_listener=True)

    def parent_apply(plugin_ctx, _config):
        parent_contexts.append(plugin_ctx)
        children.append(plugin_ctx.registry.plugin(
            lambda _child, _child_config: None,
            parent_ctx=plugin_ctx,
        ))

    loader.register_plugin_class("parent", plugin(parent_apply))
    await loader.root.update([{
        "id": "parent",
        "name": "parent",
        "inject": {"gate": {"scope": "entry"}},
    }])
    child = children[0]
    await child
    assert child.uid is not None
    assert child.entry is loader.resolve("parent")
    assert child.inject["gate"] == {"scope": "entry"}
    assert publications == [(
        child,
        child.uid,
        FiberState.PENDING,
        parent_contexts[0],
        loader.resolve("parent"),
        {"gate": {"scope": "entry"}},
    )]
