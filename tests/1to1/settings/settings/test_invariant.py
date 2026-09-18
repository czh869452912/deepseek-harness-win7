"""
1:1 test parity suite for @deepseek-ai/dsh-settings/invariant.ts.
Matching reference packages/settings/settings/tests/invariant.spec.ts.
"""

import pytest

from dsh.cordis.context import Context
from dsh.cordis.schema import Schema
from dsh.diagnostics.invariants import InvariantRegistry
from dsh.settings import invariant as SettingsInvariant
from dsh.settings.provider import settings_namespace

from .memory import MemorySettings


async def setup(with_provider: bool) -> Context:
    ctx = Context()
    await ctx.plugin(InvariantRegistry)
    await ctx.plugin(SettingsInvariant)
    if with_provider:
        await ctx.plugin(MemorySettings)
    return ctx


class TestSettingsInvariants:
    @pytest.mark.asyncio
    async def test_fails_a_settings_updated_emission_without_a_live_settings_service(self):
        ctx = await setup(False)
        with pytest.raises(Exception, match="without a live settings service"):
            ctx.emit("settings/updated", settings_namespace("ghost"), {"a": 1}, {"a": 2}, "provider")

    @pytest.mark.asyncio
    async def test_fails_a_settings_updated_emission_for_an_unregistered_namespace(self):
        ctx = await setup(True)
        with pytest.raises(Exception, match="unregistered"):
            ctx.emit("settings/updated", settings_namespace("ghost"), {"a": 1}, {"a": 2}, "provider")

    @pytest.mark.asyncio
    async def test_fails_a_settings_updated_emission_without_a_resolved_value_change(self):
        ctx = await setup(True)
        ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({
            "theme": Schema.string().default("dark"),
        }))
        with pytest.raises(Exception, match="without a resolved-value change"):
            ctx.emit("settings/updated", settings_namespace("ui-theme"), {"theme": "dark"}, {"theme": "dark"}, "update")

    @pytest.mark.asyncio
    async def test_fails_a_settings_updated_emission_whose_value_diverges_from_the_authoritative_state(self):
        ctx = await setup(True)
        ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({
            "theme": Schema.string().default("dark"),
        }))
        # Fabricated next, against the service's current resolved value ({theme: 'dark'}).
        with pytest.raises(Exception, match="authoritative"):
            ctx.emit(
                "settings/updated",
                settings_namespace("ui-theme"),
                {"theme": "forged"},
                {"theme": "dark"},
                "update",
            )
