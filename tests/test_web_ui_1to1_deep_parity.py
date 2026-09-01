"""
Dedicated 1:1 Parity Tests for Official Web GUI Frontend Integration:
1. credentials.describe flat record format
2. llm.listProviders and llm.listConfigurableProviders array schemas
3. session.modelCatalog and session.models ModelCatalog wire schema
4. agentPreset.select string RPC wire format & session/projection broadcast
5. session.selectModel RPC response & session/projection broadcast
6. Initial SSE multiplex projection push (agentPreset and modelSelection)
7. Custom models and provider definitions in settings.json / settings.yaml
"""

import json
import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionStore
from dsh.core.agent import Agent
from dsh.core.agent_loop import AgentLoopService
from dsh.llm.llm_openai import LLMOpenAIPlugin
from dsh.settings.settings_file import SettingsService
from dsh.host.webserver.webserver import WebServerService, HttpResponseWriter
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin
from dsh.host.apiproxy.api.credentials import CredentialsDomainHandler
from dsh.host.apiproxy.api.llm import LLMDomainHandler, build_model_catalog
from dsh.host.apiproxy.api.agent_presets import AgentPresetsDomainHandler
from dsh.host.apiproxy.api.sessions import SessionsDomainHandler


class MockWriter:
    def __init__(self):
        self.data = bytearray()
    def write(self, b):
        self.data.extend(b)
    async def drain(self):
        pass
    def get_json(self):
        parts = self.data.split(b"\r\n\r\n", 1)
        return json.loads(parts[1].decode("utf-8")) if len(parts) > 1 else {}
    def write_header(self, k, v):
        pass
    def write_body(self, b):
        self.data.extend(b)
    async def finish(self):
        pass
    async def send_headers(self):
        pass


@pytest.mark.asyncio
async def test_credentials_describe_flat_record_format(monkeypatch):
    """Test credentials.describe returns Record<string, CredentialInfo> without wrapper."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-env-12345")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    handler = CredentialsDomainHandler(ctx)
    res = await handler.describe_credentials({"refs": ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]})

    # Must be flat dict matching Record<string, CredentialInfo>
    assert isinstance(res, dict)
    assert "credentials" not in res
    assert "DEEPSEEK_API_KEY" in res
    assert "OPENAI_API_KEY" in res
    assert res["DEEPSEEK_API_KEY"]["configured"] is True
    assert res["DEEPSEEK_API_KEY"]["writable"] is False
    assert res["OPENAI_API_KEY"]["configured"] is False


@pytest.mark.asyncio
async def test_llm_list_providers_and_configurable_providers():
    """Test llm.listProviders and llm.listConfigurableProviders arrays for ui-settings-models."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    handler = LLMDomainHandler(ctx)

    # 1. listProviders -> LlmProviderInfo[]
    registered = await handler.list_providers({})
    assert isinstance(registered, list)
    assert len(registered) >= 1
    assert any(p["id"] == "deepseek-official" or p["id"] == "deepseek" for p in registered)

    # 2. listConfigurableProviders -> LlmConfigurableProvider[]
    directory = await handler.list_configurable_providers({})
    assert isinstance(directory, list)
    assert len(directory) >= 1
    ds_entry = next((d for d in directory if d["provider"] in ("deepseek-official", "deepseek")), None)
    assert ds_entry is not None
    assert "settingsNs" in ds_entry
    assert "settingsPath" in ds_entry
    assert isinstance(ds_entry["settingsPath"], list)


@pytest.mark.asyncio
async def test_session_model_catalog_wire_schema():
    """Test session.modelCatalog returns 1:1 ModelCatalog structure for ui-model-selection."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    catalog = await build_model_catalog(ctx)

    assert "default" in catalog
    assert "provider" in catalog["default"]
    assert "model" in catalog["default"]
    assert "routableProviders" in catalog
    assert isinstance(catalog["routableProviders"], list)
    assert "groups" in catalog
    assert isinstance(catalog["groups"], list)
    assert "failures" in catalog
    assert isinstance(catalog["failures"], list)


@pytest.mark.asyncio
async def test_agent_preset_select_and_projection_broadcast():
    """Test agentPreset.select returns preset ID string and projects to session."""
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    s = sessions.create("s-preset-test")

    events = []
    async def mock_broadcast(msg):
        events.append(msg)

    handler = AgentPresetsDomainHandler(ctx)
    # mock broadcast
    api_proxy = ApiProxyPlugin()
    api_proxy._broadcast_mux = mock_broadcast
    ctx.set_service("api_proxy", api_proxy)

    res = await handler.select_preset({"sessionId": "s-preset-test", "agentPreset": "minimal"})

    # Check return string
    assert str(res) == "minimal"
    assert res == "minimal"
    assert s.header.agent_preset == "minimal"

    # Check broadcast projection frame
    assert len(events) >= 1
    proj = next((e for e in events if e.get("type") == "session/projection" and e.get("key") == "agentPreset"), None)
    assert proj is not None
    assert proj["sessionId"] == "s-preset-test"
    assert proj["value"] == "minimal"


@pytest.mark.asyncio
async def test_session_select_model_and_projection_broadcast():
    """Test session.selectModel returns selected model and projects modelSelection."""
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    s = sessions.create("s-model-test")

    agent = Agent(session=s, ctx=ctx)
    active_sessions = {"s-model-test": type("Handle", (), {"agent": agent})()}

    events = []
    async def mock_broadcast(msg):
        events.append(msg)

    handler = SessionsDomainHandler(
        ctx=ctx,
        active_sessions=active_sessions,
        broadcast_mux=mock_broadcast,
        broadcast_host=None,
        workspaces={}
    )

    res = await handler.select_model({
        "sessionId": "s-model-test",
        "provider": "openai",
        "model": "gpt-4o",
        "reasoningEffort": "high"
    })

    assert res["selected"]["provider"] == "openai"
    assert res["selected"]["model"] == "gpt-4o"
    assert res["selected"]["reasoningEffort"] == "high"

    # Check projection frame
    assert len(events) >= 1
    proj = next((e for e in events if e.get("type") == "session/projection" and e.get("key") == "modelSelection"), None)
    assert proj is not None
    assert proj["sessionId"] == "s-model-test"
    assert proj["value"]["next"]["provider"] == "openai"
    assert proj["value"]["next"]["model"] == "gpt-4o"
    assert proj["value"]["next"]["reasoningEffort"] == "high"


@pytest.mark.asyncio
async def test_custom_user_models_in_settings_and_rpc_chain():
    """Test custom model configuration in settings binds to providers and model catalog."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    with tempfile.TemporaryDirectory() as tmpdir:
        settings = SettingsService(settings_file=os.path.join(tmpdir, "settings.json"))
        ctx.set_service("settings", settings)

        settings.set_setting("llm-openai", "providers", {
            "custom-llm": {
                "displayName": "My Custom Model Hub",
                "baseUrl": "https://custom.hub/v1",
                "apiKey": "sk-custom-secret",
                "models": [
                    {"id": "qwen-2.5-72b", "name": "Qwen 2.5 72B", "description": "Custom model 1"}
                ]
            }
        })

        handler = LLMDomainHandler(ctx)
        provs = await handler.list_providers({})
        custom_entry = next((p for p in provs if p["provider"] == "custom-llm"), None)
        assert custom_entry is not None
        assert custom_entry["displayName"] == "My Custom Model Hub"
        assert custom_entry["declared"] is True

        catalog = await build_model_catalog(ctx)
        assert "custom-llm" in catalog["routableProviders"]
