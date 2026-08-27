import pytest
import asyncio
from dsh.cordis.context import Context
from dsh.host.apiproxy.api.llm import LLMDomainHandler
from dsh.host.apiproxy.api.agent_presets import AgentPresetsDomainHandler
from dsh.host.apiproxy.api.settings import SettingsDomainHandler
from dsh.host.apiproxy.api.sessions import SessionsDomainHandler
from dsh.llm.llm_openai import LLMOpenAIPlugin
from dsh.settings.settings_file import SettingsFilePlugin
from dsh.core.agent_loop import AgentLoopPlugin, _async_iter_chunks


@pytest.mark.asyncio
async def test_llm_domain_models_and_providers():
    ctx = Context()
    await ctx.registry.plugin(LLMOpenAIPlugin, parent_ctx=ctx)
    handler = LLMDomainHandler(ctx)

    provs = await handler.list_providers({})
    assert "providers" in provs
    p_ids = [p["provider"] for p in provs["providers"]]
    assert "deepseek-official" in p_ids or "deepseek" in p_ids
    models = await handler.list_models({})
    assert "groups" in models
    assert len(models["groups"]) > 0
    group_ids = [g["id"] for g in models["groups"]]
    assert "deepseek-official" in group_ids or "deepseek" in group_ids


@pytest.mark.asyncio
async def test_session_models_uses_agent_default_selection():
    from dsh.host.apiproxy.api.sessions import SessionsDomainHandler

    class DefaultModel:
        def current_selection(self):
            return {"provider": "openai", "model": "gpt-test", "reasoningEffort": "high"}

    ctx = Context()
    ctx.set_service("agentDefaultModel", DefaultModel())
    handler = SessionsDomainHandler(ctx, {}, lambda *_a, **_k: None, lambda *_a, **_k: None, {})
    result = await handler.get_models({})
    assert result["current"] == {"provider": "openai", "model": "gpt-test", "reasoningEffort": "high"}


@pytest.mark.asyncio
async def test_agent_presets_domain():
    ctx = Context()
    handler = AgentPresetsDomainHandler(ctx)

    lst = await handler.list_presets({})
    assert "presets" in lst
    p_ids = [p["id"] for p in lst["presets"]]
    assert "minimal" in p_ids
    assert "standard" in p_ids
    assert "creative" in p_ids

    read_res = await handler.read_preset({"agentPreset": "standard"})
    assert read_res["agentPreset"] == "standard"
    assert "trust" in read_res

    select_res = await handler.select_preset({"agentPreset": "minimal"})
    assert select_res["agentPreset"] == "minimal"


@pytest.mark.asyncio
async def test_settings_domain_describe_and_update(tmp_path):
    ctx = Context()
    settings_file = str(tmp_path / "settings.yaml")
    await ctx.registry.plugin(SettingsFilePlugin, config={"path": settings_file}, parent_ctx=ctx)
    await ctx.registry.plugin(LLMOpenAIPlugin, parent_ctx=ctx)

    handler = SettingsDomainHandler(ctx)
    desc = await handler.describe_settings({})
    assert desc["writable"] is True
    assert "namespaces" in desc

    upd = await handler.update_settings({"ns": "llm", "patch": {"model": "deepseek-reasoner"}})
    assert upd["ns"] == "llm"
    assert upd["value"]["model"] == "deepseek-reasoner"


@pytest.mark.asyncio
async def test_async_iter_chunks_non_blocking():
    def sync_gen():
        yield {"type": "text-delta", "text": "hello "}
        yield {"type": "text-delta", "text": "world"}
        yield {"type": "finish", "reason": {"kind": "stop"}}

    chunks = []
    async for item in _async_iter_chunks(sync_gen()):
        chunks.append(item)

    assert len(chunks) == 3
    assert chunks[0]["text"] == "hello "
    assert chunks[1]["text"] == "world"
