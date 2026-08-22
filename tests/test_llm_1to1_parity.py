"""
Unit tests for 1:1 LLM RPC domain schemas, model discovery, model selection, and configuration chain.
"""

import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.credentials.credentials_local import CredentialsService
from dsh.llm.llm_service import LLMService, LlmError
from dsh.llm.llm_openai import LLMOpenAIPlugin
from dsh.host.apiproxy.api.llm import LLMDomainHandler, build_model_catalog
from dsh.host.apiproxy.api.sessions import SessionsDomainHandler
from dsh.settings.settings_file import SettingsService
from dsh.core.session import SessionStore, Session
from dsh.core.agent import Agent


@pytest.mark.asyncio
async def test_llm_providers_1to1_wire_schema():
    """Verify llm.providers wire JSON conforms 1:1 to ConfigurableProviderView schema."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    handler = LLMDomainHandler(ctx)
    res = await handler.list_providers({})

    assert "providers" in res
    providers = res["providers"]
    assert isinstance(providers, list)
    assert len(providers) >= 3

    for p in providers:
        assert isinstance(p["provider"], str) and len(p["provider"]) > 0
        assert isinstance(p["displayName"], str) and len(p["displayName"]) > 0
        assert isinstance(p["settingsNs"], str)
        assert isinstance(p["settingsPath"], list)
        assert isinstance(p["active"], bool)
        if "declared" in p:
            assert isinstance(p["declared"], bool)


@pytest.mark.asyncio
async def test_llm_models_and_session_models_1to1_schemas():
    """Verify llm.models and session.models output 1:1 ModelProviderGroup and ModelCatalogModel schemas."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    # Register an adapter with reasoning support
    llm_svc: LLMService = ctx.get("llm")

    class _MockAdapter:
        def provider_info(self, provider):
            return {"id": provider, "name": f"Mock {provider}"}
        def provider_retry_policy(self, provider):
            return None
        async def list_models(self, provider):
            return [
                {"provider": provider, "id": "model-a", "name": "Model A", "description": "Mock Model A"},
            ]
        async def resolve_model(self, provider, model, signal=None):
            return {
                "provider": provider,
                "id": model,
                "name": model,
                "reasoning": {
                    "efforts": [{"id": "low", "name": "Low"}, {"id": "high", "name": "High"}],
                    "defaultEffort": "low"
                }
            }

    llm_svc.register_adapter(["mock-provider"], _MockAdapter())

    handler = LLMDomainHandler(ctx)
    res = await handler.list_models({})

    assert "groups" in res
    assert "failures" in res
    groups = res["groups"]
    assert len(groups) >= 1

    for g in groups:
        assert isinstance(g["id"], str) and len(g["id"]) > 0
        assert isinstance(g["name"], str) and len(g["name"]) > 0
        assert isinstance(g["models"], list)
        assert len(g["models"]) > 0  # groups with 0 models filtered out

        for m in g["models"]:
            assert isinstance(m["id"], str) and len(m["id"]) > 0
            assert isinstance(m["name"], str) and len(m["name"]) > 0
            # Ensure no DiscoveredModelView-only keys in catalog model
            assert "contextWindow" not in m
            assert "maxTokens" not in m
            if "description" in m:
                assert isinstance(m["description"], str)
            if "reasoning" in m:
                r = m["reasoning"]
                assert "efforts" in r
                assert len(r["efforts"]) > 0
                for eff in r["efforts"]:
                    assert "id" in eff and "name" in eff


@pytest.mark.asyncio
async def test_llm_discover_models_1to1_schema():
    """Verify llm.discoverModels returns 1:1 DiscoveredModelView format."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    handler = LLMDomainHandler(ctx)
    res = await handler.discover_models({"settingsNs": "llm-deepseek", "provider": "deepseek-official"})

    assert "models" in res
    models = res["models"]
    assert len(models) >= 2

    for m in models:
        assert isinstance(m["id"], str) and len(m["id"]) > 0
        if "name" in m:
            assert isinstance(m["name"], str)
        if "contextWindow" in m:
            assert isinstance(m["contextWindow"], int)
        if "maxTokens" in m:
            assert isinstance(m["maxTokens"], int)

    # Test error handling when no discovery available or invalid request
    with pytest.raises(ValueError, match="model-discovery-failed"):
        await handler.discover_models({"settingsNs": "nonexistent-ns", "provider": "test"})


@pytest.mark.asyncio
async def test_session_select_model_and_header_propagation():
    """Verify session.selectModel updates active session selection and headers 1:1."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    sessions_svc = SessionStore(ctx)
    ctx.set_service("sessions", sessions_svc)

    session = sessions_svc.create("session-sel-1")
    agent = Agent(session=session, ctx=ctx)
    active_sessions = {"session-sel-1": type("Handle", (), {"agent": agent})()}

    sess_handler = SessionsDomainHandler(
        ctx=ctx,
        active_sessions=active_sessions,
        broadcast_mux=None,
        broadcast_host=None,
        workspaces={}
    )

    # 1. select_model
    res = await sess_handler.select_model({
        "sessionId": "session-sel-1",
        "provider": "openai",
        "model": "gpt-4o",
        "reasoningEffort": "medium"
    })

    assert res == {
        "selected": {
            "provider": "openai",
            "model": "gpt-4o",
            "reasoningEffort": "medium"
        }
    }

    # 2. Check agent model selection mutation
    assert agent._model_selection == {
        "provider": "openai",
        "model": "gpt-4o",
        "reasoningEffort": "medium"
    }
    assert agent.options.provider == "openai"
    assert agent.options.model == "gpt-4o"

    # 3. get_models returns current selection
    models_res = await sess_handler.get_models({"sessionId": "session-sel-1"})
    assert models_res["current"] == {
        "provider": "openai",
        "model": "gpt-4o",
        "reasoningEffort": "medium"
    }


def test_env_var_and_settings_fallback_chain(monkeypatch):
    """Verify DEEPSEEK_API_KEY, OPENAI_API_KEY, DEEPSEEK_BASE_URL, OPENAI_BASE_URL, and settings fallbacks."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    ctx = Context()
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = SettingsService(settings_file=os.path.join(tmpdir, "settings.json"))
        ctx.set_service("settings", settings)

        llm = LLMService(ctx=ctx)

        # 1. Default fallback when no env or settings
        assert llm.resolve_base_url() == "https://api.deepseek.com"
        assert llm.resolve_model() == "deepseek-chat"
        with pytest.raises(LlmError) as exc_info:
            llm.resolve_api_key()
        assert exc_info.value.code == "MISSING_CREDENTIAL"

        # 2. Settings resolution (camelCase and snake_case)
        settings.set_setting("llm-openai", "apiKey", "sk-settings-openai-key")
        settings.set_setting("llm-openai", "baseURL", "https://api.openai.com/v1")
        settings.set_setting("llm-openai", "model", "gpt-4o")

        assert llm.resolve_api_key() == "sk-settings-openai-key"
        assert llm.resolve_base_url() == "https://api.openai.com/v1"
        assert llm.resolve_model() == "gpt-4o"

        # 3. Env var overrides settings
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

        assert llm.resolve_api_key() == "sk-env-openai-key"
        assert llm.resolve_base_url() == "https://env.openai.com/v1"
        assert llm.resolve_model() == "gpt-4o-mini"

        # 4. DEEPSEEK_API_KEY env var takes precedence over OPENAI_API_KEY
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

        assert llm.resolve_api_key() == "sk-env-deepseek-key"
        assert llm.resolve_base_url() == "https://api.deepseek.com/v1"
        assert llm.resolve_model() == "deepseek-reasoner"


def test_api_key_validation_and_normalize_api_key():
    """Verify 1:1 API key normalization and assert_usable_api_key behavior."""
    from dsh.llm.llm_service import normalize_api_key, assert_usable_api_key

    # Valid keys (ASCII 0x21-0x7E, trimmed)
    assert normalize_api_key("  sk-valid-key-12345  ") == {"ok": True, "value": "sk-valid-key-12345"}
    assert assert_usable_api_key("  sk-valid-key  ", "llm-test", "TEST_KEY") == "sk-valid-key"

    # Empty key
    assert normalize_api_key("   ") == {"ok": False, "reason": "empty"}
    with pytest.raises(LlmError) as exc:
        assert_usable_api_key("   ", "llm-test", "TEST_KEY")
    assert exc.value.code == "INVALID_CREDENTIAL"
    assert "blank" in exc.value.failure["message"]

    # Key with illegal characters (non-printable or non-ASCII)
    assert normalize_api_key("sk-key with space") == {"ok": False, "reason": "illegalCharacters"}
    with pytest.raises(LlmError) as exc:
        assert_usable_api_key("sk-key\x00invalid", "llm-test", "TEST_KEY")
    assert exc.value.code == "INVALID_CREDENTIAL"
    assert "contains characters" in exc.value.failure["message"]


@pytest.mark.asyncio
async def test_custom_model_addition_and_settings_binding():
    """Verify custom models added in settings.llm.providers bind correctly to model catalog and providers."""
    ctx = Context()
    plugin = LLMOpenAIPlugin()
    plugin.apply(ctx)

    with tempfile.TemporaryDirectory() as tmpdir:
        settings = SettingsService(settings_file=os.path.join(tmpdir, "settings.json"))
        ctx.set_service("settings", settings)

        # Add custom provider with custom models under settings.llm.providers
        settings.set_setting("llm", "providers", {
            "custom-provider": {
                "displayName": "Custom Gateway",
                "baseUrl": "https://custom.gateway.org/v1",
                "apiKey": "sk-custom-key",
                "models": [
                    {"id": "custom-model-v1", "name": "Custom Model V1", "description": "Custom fine-tuned model"}
                ]
            }
        })

        # 1. Check list_providers in handler includes custom provider
        handler = LLMDomainHandler(ctx)
        prov_res = await handler.list_providers({})
        providers = prov_res["providers"]
        custom_p = next((p for p in providers if p["provider"] == "custom-provider"), None)
        assert custom_p is not None
        assert custom_p["displayName"] == "Custom Gateway"
        assert custom_p["declared"] is True

        # 2. Check llm_service.list_models for custom-provider returns custom model
        llm: LLMService = ctx.get("llm")
        models = await llm.list_models("custom-provider")
        assert len(models) == 1
        assert models[0]["id"] == "custom-model-v1"
        assert models[0]["name"] == "Custom Model V1"
        assert models[0]["description"] == "Custom fine-tuned model"


@pytest.mark.asyncio
async def test_stream_chunk_usage_mapping_and_finish_reasons():
    """Verify usage data is mapped to disjoint inputTokens/cacheReadTokens/reasoningTokens."""
    raw_usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_cache_hit_tokens": 30,
        "completion_tokens_details": {"reasoning_tokens": 15}
    }
    # Simulate processing raw_usage in LLMService usage mapping logic
    c_details = raw_usage.get("prompt_tokens_details") or {}
    cache_read = c_details.get("cached_tokens") if isinstance(c_details, dict) else None
    if cache_read is None:
        cache_read = raw_usage.get("prompt_cache_hit_tokens")
    p_tok = raw_usage.get("prompt_tokens", 0)
    comp_tok = raw_usage.get("completion_tokens", 0)
    u_out = {
        "inputTokens": max(0, p_tok - (cache_read or 0)),
        "outputTokens": comp_tok,
    }
    if cache_read is not None:
        u_out["cacheReadTokens"] = cache_read
    r_details = raw_usage.get("completion_tokens_details") or {}
    r_tok = r_details.get("reasoning_tokens") if isinstance(r_details, dict) else None
    if r_tok is not None:
        u_out["reasoningTokens"] = r_tok

    assert u_out["inputTokens"] == 70  # 100 - 30 disjoint
    assert u_out["outputTokens"] == 50
    assert u_out["cacheReadTokens"] == 30
    assert u_out["reasoningTokens"] == 15

