"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent/model-selection,
@deepseek-ai/dsh-agent-default-model, and @deepseek-ai/dsh-agent-tool-presentation.
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.agent_default_model import AgentDefaultModelConfig, AgentDefaultModelPlugin, AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE
from dsh.core.agent_tool_presentation import AgentToolPresentationPlugin
from dsh.core.model_selection import ModelSelection, ModelSelectionRef, install_model_selection
from dsh.core.session import Session
from dsh.core.tools import ToolsService, Tool


# ============================================================================
# 1. install_model_selection (from agent/tests/model-selection.spec.ts)
# ============================================================================

@pytest.mark.asyncio
async def test_install_model_selection_snapshots_variables_and_request_routing():
    ctx = Context()
    selection = ModelSelectionRef(current=None, assembled=None)
    dispose = install_model_selection(ctx, selection)

    seed_assembly = {"variables": {}}
    res_assembly = await ctx.waterfall("system-prompt/assemble", seed_assembly, None)
    assert res_assembly.get("variables", {}) == {}

    seed_request = {"provider": "seed", "model": "seed", "temperature": 0.2}
    res_req = await ctx.waterfall("agent/request", seed_request)
    assert res_req == seed_request

    # 1. Set current selection with reasoning effort
    selection.current = ModelSelection(provider="alpha", model="a1", reasoning_effort="high")
    res_assembly2 = await ctx.waterfall("system-prompt/assemble", {"variables": {}}, None)
    assert res_assembly2["variables"]["provider"] == "alpha"
    assert res_assembly2["variables"]["model"] == "a1"

    # Next step request uses assembled selection
    selection.current = ModelSelection(provider="beta", model="b1")
    res_req2 = await ctx.waterfall("agent/request", dict(seed_request))
    assert res_req2 == {
        "provider": "alpha",
        "model": "a1",
        "reasoningEffort": "high",
        "temperature": 0.2,
    }

    # Next assembly captures beta/b1
    res_assembly3 = await ctx.waterfall("system-prompt/assemble", {"variables": {}}, None)
    assert res_assembly3["variables"]["provider"] == "beta"
    assert res_assembly3["variables"]["model"] == "b1"

    inherited = {"provider": "alpha", "model": "a1", "reasoningEffort": "max", "temperature": 0.2}
    res_req3 = await ctx.waterfall("agent/request", inherited)
    assert res_req3 == {"provider": "beta", "model": "b1", "temperature": 0.2}

    # Dispose unregisters both listeners
    dispose()
    res_assembly_after = await ctx.waterfall("system-prompt/assemble", {"variables": {}}, None)
    assert res_assembly_after.get("variables", {}) == {}

    res_req_after = await ctx.waterfall("agent/request", dict(seed_request))
    assert res_req_after == seed_request


# ============================================================================
# 2. AgentDefaultModelConfig (from agent-default-model/tests/agent-default-model.spec.ts)
# ============================================================================

class MockSettingsService:
    def __init__(self):
        self.doc = {}

    def get(self, ns):
        return self.doc.get(ns)

    async def replace(self, ns, section):
        self.doc[ns] = dict(section)


@pytest.mark.asyncio
async def test_agent_default_model_config_lifecycle():
    ctx = Context()
    settings = MockSettingsService()
    ctx.set_service("settings", settings)

    default_model = AgentDefaultModelConfig(ctx, {"provider": "deepseek-official", "model": "deepseek-v4-flash"})
    ctx.set_service("agent_default_model", default_model)

    assert default_model.current_selection() == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
    }

    # Save selection
    await default_model.save_selection(ModelSelection(provider="acme-gateway", model="acme-large", reasoning_effort="high"))
    assert default_model.current_selection() == {
        "provider": "acme-gateway",
        "model": "acme-large",
        "reasoningEffort": "high",
    }

    # Clear effort
    await default_model.save_selection(ModelSelection(provider="acme-gateway", model="acme-plain"))
    assert default_model.current_selection() == {
        "provider": "acme-gateway",
        "model": "acme-plain",
    }


# ============================================================================
# 3. AgentToolPresentationPlugin (from agent-tool-presentation/tests/agent-tool-presentation.spec.ts)
# ============================================================================

@pytest.mark.asyncio
async def test_agent_tool_presentation_modes():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    plugin_native = AgentToolPresentationPlugin({"mode": "native"})
    ctx.set_service("codeRuntime", object())
    plugin_ptc = AgentToolPresentationPlugin({"mode": "ptc"})
    plugin_ptc.apply(ctx)
    assert getattr(tools, "_presentation_mode", "native") == "ptc"
