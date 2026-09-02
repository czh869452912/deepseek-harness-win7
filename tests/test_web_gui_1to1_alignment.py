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
    ctx.plugin(LLMOpenAIPlugin)
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
    ctx.plugin(SettingsFilePlugin, config={"path": settings_file})
    ctx.plugin(LLMOpenAIPlugin)

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


@pytest.mark.asyncio
async def test_client_modules_v012_alpha_roster_and_bundles():
    import os
    from dsh.host.client_modules.registry import ClientModuleRegistry, OFFICIAL_WEB_ROSTER

    ctx = Context()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkgs_dir = os.path.join(repo_root, "packages")
    registry = ClientModuleRegistry(ctx, search_dirs=[pkgs_dir])
    registry.scan_packages()

    g = registry.graph()
    assert g is not None
    assert "entries" in g
    entries = g["entries"]
    assert len(entries) > 30

    ids = [e["id"] for e in entries]
    assert "@deepseek-ai/dsh-client-ui-approval" in ids
    assert "@deepseek-ai/dsh-client-ui-chat" in ids
    assert "@deepseek-ai/dsh-client-ui-session" in ids
    assert "@deepseek-ai/dsh-client-connection" in ids
    assert "@deepseek-ai/dsh-client-modules" in ids

    # Verify every composed plugin has valid hash and bundle
    for entry in entries:
        assert entry["rev"] != "000000000000"
        path = registry.client_path(entry["id"])
        assert path is not None
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 0


