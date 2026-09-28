import pytest
import asyncio
import copy

from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.llm.deepseek_config import resolve_options
from dsh.cordis.context import Context
from dsh.llm.llm_deepseek import DeepSeekAdapter, LLMDeepSeekPlugin
from dsh.llm.llm_service import LLMService, LlmRuntime
from dsh.settings.provider import SettingsProvider


def environment():
    return LaunchEnvironmentSnapshot([{"source": "process", "values": {"DEEPSEEK_BASE_URL": "http://localhost:1"}}])


@pytest.mark.parametrize("config", [
    {"thinking": "disabled", "reasoningEffort": "high"},
    {"maxTokens": True}, {"streamIdleTimeoutMs": float("inf")},
    {"models": [{"id": "a"}, {"id": "a"}]},
    {"models": [{"id": "a", "inputModalities": ["image", "image"]}]},
    {"models": [{"id": "a", "imagePixelBudget": 1}]},
    {"fileExpiresAfterSeconds": 3600, "fileRefreshMarginSeconds": 3600},
    {"maxImagesPerRequest": 1}, {"maxRequestFilesBytes": 1},
    {"maxInlineRequestImageBytes": 1}, {"fileQuotaCleanupBatch": 1001},
])
def test_invalid_complete_connection_is_rejected(config):
    with pytest.raises((ValueError, TypeError)):
        resolve_options(config, environment())


def test_catalog_and_policy_are_detached_and_environment_is_used():
    config = {"models": [{"id": "vision", "inputModalities": ["text", "image"], "imagePixelBudget": "low"}]}
    options = resolve_options(config, environment())
    assert options["baseURL"] == "http://localhost:1"
    assert options["models"][0]["imagePixelBudget"] == 512 * 512
    assert options["retryPolicy"]["mode"] == "normal"
    config["models"][0]["id"] = "changed"
    assert options["models"][0]["id"] == "vision"
    assert resolve_options({}, environment())["models"][-1]["inputModalities"] == ["text", "image"]


class MemorySettings(SettingsProvider):
    def _load_document(self):
        return copy.deepcopy(self._document)

    def _persist_section(self, ns, section):
        self._document = dict(self._document, **{ns: copy.deepcopy(section)})


@pytest.mark.asyncio
async def test_live_settings_replace_route_atomically_and_invalid_generation_keeps_endpoint_and_ref():
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    settings_fiber = await ctx.plugin(MemorySettings)
    await ctx.plugin(LLMDeepSeekPlugin, config={"baseURL": "http://old", "apiKeyEnv": "OLD_KEY"})
    try:
        llm, settings = ctx.get("llm"), ctx.get("settings")
        snapshots = []
        ctx.on("llm/adapters-updated", lambda: snapshots.append(llm.list_providers()))
        await settings.replace("llm-deepseek", {"baseURL": "http://new", "apiKeyEnv": "NEW_KEY", "retryPolicy": {"mode": "always"}})
        await asyncio.sleep(0)
        adapter = llm._adapters["deepseek-official"]["adapter"]
        assert llm.retry_policy("deepseek-official")["mode"] == "always"
        assert snapshots and all([row["id"] for row in snap] == ["deepseek-official"] for snap in snapshots)
        with pytest.raises(ValueError):
            await settings.replace("llm-deepseek", {"baseURL": "http://bad", "apiKeyEnv": "BAD_KEY", "maxTokens": -1})
        assert adapter.options()["baseURL"] == "http://new"
        assert adapter.options()["apiKeyEnv"] == "NEW_KEY"
        await settings_fiber.dispose()
        assert adapter.options()["baseURL"] == "http://old"
        assert llm.retry_policy("deepseek-official")["mode"] == "normal"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_prepared_stream_pins_whole_generation_and_model_token_cap(monkeypatch, caplog):
    ctx = Context()
    ctx.set_service("launchEnvironment", LaunchEnvironmentSnapshot([{"source": "process", "values": {"OLD_KEY": "old-secret", "NEW_KEY": "new-secret"}}]))
    current = {"baseURL": "http://old", "apiKeyEnv": "OLD_KEY", "models": [{"id": "model", "maxTokens": 7}]}
    adapter = DeepSeekAdapter(ctx, current)
    adapter.source = lambda: current
    captured = []
    def transport(self, messages, **kwargs):
        captured.append((self.resolve_base_url(), self.resolve_api_key(), kwargs["options"]["maxTokens"]))
        return iter([])
    monkeypatch.setattr(LLMService, "_default_chat_completion_stream", transport)
    prepared = await adapter.prepare_call("deepseek-official", "model")
    current = {"baseURL": "http://new", "apiKeyEnv": "NEW_KEY", "maxTokens": 99}
    list(prepared["stream"]({"model": "model", "messages": []}))
    list(adapter.stream({"model": "model", "messages": []}))
    assert captured == [("http://old", "old-secret", 7), ("http://new", "new-secret", 99)]
    current = {"baseURL": "http://invalid", "apiKeyEnv": "INVALID_KEY", "maxTokens": 0}
    list(adapter.stream({"model": "model", "messages": []}))
    list(adapter.stream({"model": "model", "messages": []}))
    assert captured[-1] == captured[-2] == ("http://new", "new-secret", 99)
    assert caplog.text.count("Keeping the last good configuration") == 1
