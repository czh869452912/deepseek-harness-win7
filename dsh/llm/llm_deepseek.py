"""Native DeepSeek provider registration; request facts are resolved per call."""
import copy
import os

from dsh.cordis.plugin import Plugin
from dsh.llm.llm_service import LLMService, LlmError, assert_usable_api_key


class DeepSeekAdapter:
    def __init__(self, ctx, config):
        self.ctx, self.config = ctx, dict(config)

    def options(self):
        options = dict(self.config)
        settings = self.ctx.get("settings")
        saved = settings.get("llm-deepseek") if settings is not None else None
        if isinstance(saved, dict):
            options.update(saved)
        return options

    def provider_info(self, provider):
        return {"id": provider, "name": "DeepSeek"}

    def provider_retry_policy(self, provider):
        from dsh.llm.retry_policy import resolve_retry_policy
        return resolve_retry_policy(self.options().get("retryPolicy"))

    async def list_models(self, provider):
        options = self.options()
        models = options.get("models", [
            {"id": "deepseek-v4-flash", "name": "DeepSeek-V4-Flash"},
            {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro"}])
        return [dict(copy.deepcopy(model), provider=provider,
                     contextWindow=model.get("contextWindow", options.get("defaultContextWindow", 1000000)))
                for model in models]

    async def resolve_model(self, provider, model, signal=None):
        options = self.options()
        info = next((row for row in await self.list_models(provider) if row["id"] == model),
                    {"provider": provider, "id": model, "name": model,
                     "contextWindow": options.get("defaultContextWindow", 1000000)})
        info["defaultMaxTokens"] = info.get("maxTokens", options.get("maxTokens", 256000))
        info["reasoning"] = {"supported": True, "efforts": ["off", "low", "high", "max"],
                             "defaultEffort": options.get("reasoningEffort", "off" if options.get("thinking") == "disabled" else "high")}
        return info

    def stream(self, request):
        options = self.options()
        ref = options.get("apiKeyEnv", "DEEPSEEK_API_KEY")
        credentials = self.ctx.get("credentials")
        hit = credentials.resolve(ref) if credentials is not None else None
        value = hit.get("value") if isinstance(hit, dict) else getattr(hit, "value", None)
        environment = self.ctx.get("launch_environment")
        ambient = environment.get(ref) if environment is not None else None
        if value is None:
            value = getattr(ambient, "value", None) if environment is not None else os.environ.get(ref)
        if not value:
            raise LlmError("No API key for deepseek-official; configure {} in credentials or the launch environment".format(ref), "MISSING_CREDENTIAL")
        endpoint = environment.get("DEEPSEEK_BASE_URL") if environment is not None else None
        base_url = options.get("baseURL") or (getattr(endpoint, "value", None) if environment is not None else os.environ.get("DEEPSEEK_BASE_URL")) or "https://api.deepseek.com"
        transport = LLMService(api_key=assert_usable_api_key(value, "llm-deepseek", ref), base_url=base_url)
        resolved = dict(request)
        resolved.setdefault("reasoningEffort", options.get("reasoningEffort", "off" if options.get("thinking") == "disabled" else "high"))
        resolved.setdefault("maxTokens", options.get("maxTokens", 256000))
        if options.get("thinking") == "disabled" and resolved["reasoningEffort"] != "off":
            raise LlmError("This DeepSeek deployment disables thinking", "UNSUPPORTED_REASONING_EFFORT")
        return transport._default_chat_completion_stream(
            resolved["messages"], tools=resolved.get("tools"), model=resolved["model"],
            system=resolved.get("system"), temperature=resolved.get("temperature"), options=resolved)


class LLMDeepSeekPlugin(Plugin):
    id = "llm-deepseek"
    inject = ["llm"]

    def apply(self, ctx):
        llm = ctx.get("llm")
        adapter = DeepSeekAdapter(ctx, self.config)
        dispose_route = llm.register_adapter(["deepseek-official"], adapter)
        dispose_directory = llm.register_configurable_providers([
            {"provider": "deepseek-official", "displayName": "DeepSeek", "settingsNs": "llm-deepseek", "settingsPath": []}])

        async def discover(_request):
            return [{k: v for k, v in row.items() if k != "provider"}
                    for row in await adapter.list_models("deepseek-official")]

        dispose_discovery = llm.register_model_discovery("llm-deepseek", discover)
        ctx.effect(lambda: dispose_route)
        ctx.effect(lambda: dispose_directory)
        ctx.effect(lambda: dispose_discovery)
