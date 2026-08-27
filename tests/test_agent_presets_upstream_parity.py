import os
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.presets import AgentPresets, Config, PresetMountError, PresetRoot
from dsh.presets import (
    AgentPreset,
    PresetNotWritableError,
    delete_composition,
    read_preset_metadata,
    render_preset_metadata,
    resolve_session_preset,
)
from dsh.presets import live_preset_mounts
from dsh.settings.provider import SettingsProvider


def seed(root, preset_id, rows):
    directory = Path(root) / preset_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "agent.cordis.yml").write_text(rows, encoding="utf-8")


async def boot(tmp_path, plugins):
    ctx = Context()
    ctx.baseUrl = str(tmp_path)
    loader_fiber = ctx.registry.plugin(Loader, {"baseUrl": str(tmp_path)})
    await loader_fiber
    loader = ctx.get("loader")
    for name, plugin in plugins.items():
        loader.register_plugin_class(name, plugin)
    preset_fiber = ctx.registry.plugin(
        AgentPresets,
        {
            "default": "alpha",
            "roots": [{"path": str(tmp_path), "trust": "user"}],
            "includeUserRoot": False,
        },
    )
    await preset_fiber
    return ctx, preset_fiber, ctx.get("agentPresets")


@pytest.mark.asyncio
async def test_real_loader_mount_is_single_flight_shared_and_recomposable(tmp_path):
    calls = []

    def contribute(_ctx, config):
        calls.append(config["label"])

    seed(tmp_path, "alpha", "- id: alpha\n  name: fixture:contribute\n  config:\n    label: alpha\n")
    seed(tmp_path, "beta", "- id: beta\n  name: fixture:contribute\n  config:\n    label: beta\n")
    ctx, _fiber, presets = await boot(tmp_path, {"fixture:contribute": contribute})
    first = ctx.extend()
    second = ctx.extend()

    await presets.mount(first, "alpha")
    await presets.mount(second, "alpha")
    assert calls == ["alpha"]
    assert presets.composed_preset(first) == "alpha"
    assert presets.composed_preset(second) == "alpha"
    assert first._parent is second._parent

    await presets.recompose(first, "beta")
    assert calls == ["alpha", "beta"]
    assert presets.composed_preset(first) == "beta"
    assert presets.composed_preset(second) == "alpha"
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_recompose_keeps_previous_generation(tmp_path):
    seed(tmp_path, "alpha", "[]\n")
    seed(tmp_path, "broken", "- id: missing\n  name: fixture:missing\n")
    ctx, _fiber, presets = await boot(tmp_path, {})
    agent_ctx = ctx.extend()
    await presets.mount(agent_ctx, "alpha")

    with pytest.raises(PresetMountError):
        await presets.recompose(agent_ctx, "broken")
    assert presets.composed_preset(agent_ctx) == "alpha"
    await ctx.fiber.dispose()


def test_discovery_only_treats_directories_as_preset_slots(tmp_path):
    from dsh.presets import scan_root

    (tmp_path / "stray.yaml").write_text("[]\n", encoding="utf-8")
    seed(tmp_path, "real", "[]\n")
    assert [item.id for item in scan_root(PresetRoot(str(tmp_path), "user"))] == ["real"]


def test_non_directory_root_fails_loud(tmp_path):
    from dsh.presets import scan_root

    path = tmp_path / "not-a-directory"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match="cannot read preset root"):
        scan_root(PresetRoot(str(path), "user"))


def test_metadata_ignores_non_finite_order_and_renders_integer_stably(tmp_path):
    (tmp_path / "preset.yml").write_text("order: .inf\n", encoding="utf-8")
    assert read_preset_metadata(str(tmp_path)) == {}
    assert render_preset_metadata({"name": "Standard", "order": 1}) == "name: Standard\norder: 1\n"


def test_delete_rejects_a_sibling_that_only_shares_the_writable_prefix(tmp_path):
    writable = tmp_path / "user"
    sibling = tmp_path / "user-escape" / "mine"
    sibling.mkdir(parents=True)
    composition = sibling / "agent.cordis.yml"
    composition.write_text("[]\n", encoding="utf-8")
    preset = AgentPreset("mine", "user", str(composition))
    with pytest.raises(PresetNotWritableError, match="does not live under"):
        delete_composition([PresetRoot(str(writable), "user")], preset)
    assert composition.exists()


class MemorySettings(SettingsProvider):
    def __init__(self, ctx, _config=None):
        super().__init__(ctx)

    def _load_document(self):
        return dict(self._document)

    def _persist_section(self, ns, section):
        self._document[ns] = dict(section)


@pytest.mark.asyncio
async def test_settings_default_is_live_and_detach_falls_back(tmp_path):
    seed(tmp_path, "alpha", "[]\n")
    seed(tmp_path, "beta", "[]\n")
    ctx = Context()
    ctx.baseUrl = str(tmp_path)
    loader_fiber = ctx.registry.plugin(Loader, {"baseUrl": str(tmp_path)})
    await loader_fiber
    preset_fiber = ctx.registry.plugin(
        AgentPresets,
        {"default": "alpha", "roots": [{"path": str(tmp_path)}], "includeUserRoot": False},
    )
    await preset_fiber
    presets = ctx.get("agentPresets")
    assert presets.default_id == "alpha"

    settings_fiber = ctx.registry.plugin(MemorySettings, {})
    await settings_fiber
    settings_fiber.ctx.get("settings").update("agent-presets", {"default": "beta"})
    assert presets.default_id == "beta"
    await settings_fiber.dispose()
    assert presets.default_id == "alpha"
    await ctx.fiber.dispose()


def test_session_resolution_accepts_mapping_and_last_logged_selection():
    session = {
        "header": {"agentPreset": "alpha"},
        "events": [
            {"type": "agent-preset/selected", "data": {"agentPreset": "beta"}},
            {"type": "agent-preset/selected", "data": {"agentPreset": "gamma"}},
        ],
    }
    assert resolve_session_preset(session) == "gamma"


@pytest.mark.asyncio
async def test_pending_dependency_is_rejected_without_hanging(tmp_path):
    class Pending:
        inject = ["neverAvailable"]

        def __call__(self, _ctx):
            raise AssertionError("pending plugin must not run")

    seed(tmp_path, "alpha", "- id: pending\n  name: fixture:pending\n")
    ctx, _fiber, presets = await boot(tmp_path, {"fixture:pending": Pending()})
    with pytest.raises(PresetMountError, match="waiting for neverAvailable"):
        await presets.mount(ctx.extend(), "alpha")
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_relative_python_plugin_and_file_edit_start_new_generation(tmp_path):
    calls_file = tmp_path / "calls.txt"
    plugin = tmp_path / "plugin.py"
    plugin.write_text(
        "def default(ctx, config):\n"
        "    with open(config['output'], 'a', encoding='utf-8') as handle:\n"
        "        handle.write(config['label'] + '\\n')\n",
        encoding="utf-8",
    )
    seed(
        tmp_path,
        "alpha",
        "- id: relative\n  name: ../plugin.py\n  config:\n    output: %s\n    label: first\n"
        % str(calls_file).replace("\\", "/"),
    )
    ctx, _fiber, presets = await boot(tmp_path, {})
    first = ctx.extend()
    await presets.mount(first, "alpha")
    composition = tmp_path / "alpha" / "agent.cordis.yml"
    composition.write_text(
        "- id: relative\n  name: ../plugin.py\n  config:\n    output: %s\n    label: second-generation\n"
        % str(calls_file).replace("\\", "/"),
        encoding="utf-8",
    )
    second = ctx.extend()
    await presets.mount(second, "alpha")
    assert calls_file.read_text(encoding="utf-8").splitlines() == ["first", "second-generation"]
    assert presets.composed_preset(first) == "alpha"
    assert first._parent is not second._parent
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_global_service_leak_rejected_and_isolated_service_addressable(tmp_path):
    def provider(ctx, config):
        ctx.provide(config["name"], {"label": config["label"]})

    seed(
        tmp_path,
        "leaky",
        "- id: leak\n  name: fixture:provider\n  config:\n    name: leakedSvc\n    label: bad\n",
    )
    seed(
        tmp_path,
        "isolated",
        "- id: private\n  name: fixture:provider\n  isolate:\n    privateSvc: true\n"
        "  config:\n    name: privateSvc\n    label: shared\n",
    )
    ctx, _fiber, presets = await boot(tmp_path, {"fixture:provider": provider})
    with pytest.raises(PresetMountError, match="process-global service.*leakedSvc"):
        await presets.mount(ctx.extend(), "leaky")

    agent_ctx = ctx.extend()
    await presets.mount(agent_ctx, "isolated")
    agent = type("Agent", (), {"ctx": agent_ctx})()
    assert ctx.get("privateSvc", None) is None
    assert presets.service_for(agent, "privateSvc") == {"label": "shared"}
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_roster_fiber_owns_standing_mounts_and_settings_registration(tmp_path):
    seed(tmp_path, "alpha", "[]\n")
    ctx = Context()
    ctx.baseUrl = str(tmp_path)
    loader_fiber = ctx.registry.plugin(Loader, {"baseUrl": str(tmp_path)})
    await loader_fiber
    settings_fiber = ctx.registry.plugin(MemorySettings, {})
    await settings_fiber
    preset_fiber = ctx.registry.plugin(
        AgentPresets,
        {"default": "alpha", "roots": [{"path": str(tmp_path)}], "includeUserRoot": False},
    )
    await preset_fiber
    presets = ctx.get("agentPresets")
    await presets.mount(ctx.extend(), "alpha")
    assert any(mount.preset_id == "alpha" for mount in live_preset_mounts())

    settings = settings_fiber.ctx.get("settings")
    await preset_fiber.dispose()
    assert ctx.get("agentPresets", None) is None
    assert not any(mount.preset_id == "alpha" for mount in live_preset_mounts())
    assert "agent-presets" not in settings._registrations
    await ctx.fiber.dispose()
