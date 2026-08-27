import asyncio
import copy
import inspect

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.core import agent_default_model_invariant
from dsh.core.model_selection import (
    AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE,
    AgentDefaultModelConfig,
)
from dsh.settings.provider import SettingsProvider


class MemorySettings(SettingsProvider):
    def __init__(self, ctx, _config=None):
        super().__init__(ctx)

    def _load_document(self):
        return copy.deepcopy(self._document)

    def _persist_section(self, ns, section):
        self._document = dict(self._document, **{ns: copy.deepcopy(section)})


async def boot():
    ctx = Context()
    settings_fiber = ctx.registry.plugin(MemorySettings, {})
    await settings_fiber
    default_fiber = ctx.registry.plugin(
        AgentDefaultModelConfig,
        {"provider": "deepseek-official", "model": "deepseek-v4-flash"},
    )
    await default_fiber
    return ctx, settings_fiber, default_fiber, ctx.get("agentDefaultModel")


@pytest.mark.asyncio
async def test_resolves_user_layer_and_returns_detached_selection():
    ctx, _settings_fiber, _default_fiber, service = await boot()
    assert service.current_selection() == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
    }

    await service.save_selection(
        {"provider": "acme-gateway", "model": "acme-large", "reasoningEffort": "high"}
    )
    first = service.current_selection()
    first["provider"] = "mutated"
    assert service.current_selection() == {
        "provider": "acme-gateway",
        "model": "acme-large",
        "reasoningEffort": "high",
    }
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_complete_save_clears_a_stored_reasoning_effort():
    ctx, _settings_fiber, _default_fiber, service = await boot()
    await service.save_selection(
        {"provider": "acme-gateway", "model": "acme-large", "reasoningEffort": "high"}
    )
    await service.save_selection({"provider": "acme-gateway", "model": "acme-plain"})
    assert service.current_selection() == {"provider": "acme-gateway", "model": "acme-plain"}
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_selection_preserves_an_explicit_none_reasoning_effort():
    ctx = Context()
    fiber = ctx.registry.plugin(
        AgentDefaultModelConfig, {"provider": "entry", "model": "entry-model"}
    )
    await fiber
    service = ctx.get("agentDefaultModel")
    service._source = lambda: {
        "provider": "entry",
        "model": "entry-model",
        "reasoningEffort": None,
    }

    assert service.currentSelection() == {
        "provider": "entry",
        "model": "entry-model",
        "reasoningEffort": None,
    }
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_camel_api_saves_and_reads_the_complete_selection():
    ctx, _settings_fiber, _default_fiber, service = await boot()
    await service.saveSelection(
        {"provider": "camel-provider", "model": "camel-model", "reasoningEffort": "max"}
    )
    assert service.currentSelection() == {
        "provider": "camel-provider",
        "model": "camel-model",
        "reasoningEffort": "max",
    }
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_partial_stored_section_layers_over_composition_entry():
    ctx, settings_fiber, _default_fiber, service = await boot()
    settings_fiber.ctx.get("settings").replace(
        AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE, {"model": "deepseek-reasoner"}
    )
    assert service.current_selection() == {
        "provider": "deepseek-official",
        "model": "deepseek-reasoner",
    }
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_external_settings_publish_is_live_and_detach_falls_back_to_entry():
    ctx, settings_fiber, _default_fiber, service = await boot()
    settings = settings_fiber.ctx.get("settings")
    settings.publish(
        {
            AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE: {
                "provider": "external",
                "model": "published",
                "reasoningEffort": "medium",
            }
        }
    )
    assert service.current_selection() == {
        "provider": "external",
        "model": "published",
        "reasoningEffort": "medium",
    }

    await settings_fiber.dispose()
    assert service.current_selection() == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
    }
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_without_settings_save_is_noop_and_opaque_routes_are_accepted():
    ctx = Context()
    fiber = ctx.registry.plugin(AgentDefaultModelConfig, {"provider": "unknown", "model": "no-route"})
    await fiber
    service = ctx.get("agentDefaultModel")
    await service.save_selection({"provider": "other", "model": "other"})
    assert service.current_selection() == {"provider": "unknown", "model": "no-route"}
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_settings_provider_mounted_late_becomes_the_live_source():
    ctx = Context()
    default_fiber = ctx.registry.plugin(
        AgentDefaultModelConfig, {"provider": "entry", "model": "entry-model"}
    )
    await default_fiber
    service = ctx.get("agentDefaultModel")

    settings_fiber = ctx.registry.plugin(MemorySettings, {})
    await settings_fiber
    await service.save_selection({"provider": "saved", "model": "saved-model"})
    assert service.current_selection() == {"provider": "saved", "model": "saved-model"}
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_settings_provider_can_detach_and_be_replaced():
    ctx = Context()
    default_fiber = ctx.registry.plugin(
        AgentDefaultModelConfig, {"provider": "entry", "model": "entry-model"}
    )
    await default_fiber
    service = ctx.get("agentDefaultModel")

    first = ctx.registry.plugin(MemorySettings, {})
    await first
    await service.saveSelection({"provider": "first", "model": "first-model"})
    assert service.currentSelection()["provider"] == "first"
    await first.dispose()
    assert service.currentSelection()["provider"] == "entry"

    second = ctx.registry.plugin(MemorySettings, {})
    await second
    await service.saveSelection({"provider": "second", "model": "second-model"})
    assert service.currentSelection() == {"provider": "second", "model": "second-model"}
    await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {},
        {"provider": "p"},
        {"model": "m"},
        {"provider": 1, "model": "m"},
        {"provider": "p", "model": None},
    ],
)
async def test_config_requires_string_provider_and_model(config):
    ctx = Context()
    fiber = ctx.registry.plugin(AgentDefaultModelConfig, config)
    with pytest.raises((TypeError, ValueError)):
        await fiber
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_default_model_fiber_owns_service_and_settings_registration():
    ctx, settings_fiber, default_fiber, _service = await boot()
    settings = settings_fiber.ctx.get("settings")
    assert AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE in settings._registrations
    await default_fiber.dispose()
    assert ctx.get("agentDefaultModel") is None
    assert AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE not in settings._registrations
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_settings_registration_effect_belongs_to_the_injected_consumer_child():
    ctx, settings_fiber, default_fiber, _service = await boot()
    settings = settings_fiber.ctx.get("settings")
    mount_fiber = next(fiber for fiber in ctx.registry.list_fibers() if fiber.name == "_mount")

    provider_labels = [effect["label"] for effect in settings_fiber.get_effects()]
    mount_labels = [effect["label"] for effect in mount_fiber.get_effects()]
    assert "settings.register(agent-default-model)" not in provider_labels
    assert "settings.register(agent-default-model)" in mount_labels

    await default_fiber.dispose()
    assert ctx.get("settings") is settings
    assert AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE not in settings._registrations
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_duplicate_service_does_not_disturb_the_first_registration():
    ctx, _settings_fiber, first_fiber, first_service = await boot()
    duplicate = ctx.registry.plugin(
        AgentDefaultModelConfig, {"provider": "second", "model": "second-model"}
    )
    with pytest.raises(RuntimeError, match="has been registered"):
        await duplicate

    assert ctx.get("agentDefaultModel") is first_service
    assert first_service.currentSelection() == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
    }
    assert AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE in ctx.get("settings")._registrations
    await first_fiber.dispose()
    await ctx.fiber.dispose()


def test_default_model_cleanup_does_not_reach_into_settings_private_storage():
    source = inspect.getsource(AgentDefaultModelConfig)
    assert "_registrations" not in source


@pytest.mark.asyncio
async def test_invariant_companion_waits_for_service_and_registers_empty_installer():
    ctx = Context()
    fiber = ctx.registry.plugin(agent_default_model_invariant)
    await asyncio.sleep(0)
    assert fiber.state == FiberState.PENDING

    calls = []
    disposed = []

    class Invariants:
        def register(self, package_name, installer):
            calls.append((package_name, installer))
            return lambda: disposed.append(package_name)

    ctx.provide("invariants", Invariants())
    await fiber

    assert agent_default_model_invariant.name == "agent-default-model-invariant"
    assert agent_default_model_invariant.inject == ["invariants"]
    assert calls[0][0] == "@deepseek-ai/dsh-agent-default-model"
    calls[0][1](fiber.ctx, lambda _message: None)

    await fiber.dispose()
    assert disposed == ["@deepseek-ai/dsh-agent-default-model"]
    await ctx.fiber.dispose()
