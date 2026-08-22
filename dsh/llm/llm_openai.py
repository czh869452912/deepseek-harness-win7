from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.llm.llm_service import LLMService


class LLMOpenAIPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-llm-openai`: Mounts LLM service for DeepSeek / OpenAI compatible API.
    """

    id = "llm-openai"
    name = "@deepseek-ai/dsh-llm-openai"

    def apply(self, ctx: Any) -> None:
        api_key = self.config.get("api_key")
        base_url = self.config.get("base_url")
        model = self.config.get("model")
        api_key_env = self.config.get("apiKeyEnv", "DEEPSEEK_API_KEY")

        llm_service = LLMService(
            ctx=ctx,
            api_key=api_key,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env
        )
        ctx.set_service("llm", llm_service)

        # 1:1 with llm-deepseek index.ts: register configurable provider directory
        # provider deepseek-official -> settingsNs llm-deepseek, openai -> llm-openai
        try:
            llm_service.register_configurable_providers([
                {"provider": "deepseek-official", "displayName": "DeepSeek", "settingsNs": "llm-deepseek", "settingsPath": []},
                {"provider": "deepseek", "displayName": "DeepSeek Official", "settingsNs": "llm", "settingsPath": []},
                {"provider": "openai", "displayName": "OpenAI Compatible", "settingsNs": "llm-openai", "settingsPath": []},
            ])
        except Exception:
            pass

        # Register a minimal adapter for each provider so listProviders/active is correct
        class _SimpleAdapter:
            def provider_info(self, provider):
                names = {"deepseek-official": "DeepSeek", "deepseek": "DeepSeek Official", "openai": "OpenAI Compatible"}
                return {"id": provider, "name": names.get(provider, provider)}
            def provider_retry_policy(self, provider):
                return None
            async def list_models(self, provider):
                if provider in ("deepseek", "deepseek-official"):
                    return [
                        {"provider": provider, "id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "description": "High efficiency general reasoning"},
                        {"provider": provider, "id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)", "description": "Deep reasoning"},
                    ]
                return []
            async def resolve_model(self, provider, model, signal=None):
                return {"provider": provider, "id": model, "name": model}

        try:
            adapter = _SimpleAdapter()
            llm_service.register_adapter(["deepseek-official", "deepseek", "openai"], adapter)
        except Exception:
            pass

        # Register model discovery (1:1 with LlmRuntime.registerModelDiscovery)
        async def _discover(request):
            # If provider known, return its catalog, else probe baseURL via OpenAI /models
            provider = request.get("provider") if isinstance(request, dict) else None
            if provider and provider in ("deepseek", "deepseek-official", "openai"):
                try:
                    models = await adapter.list_models(provider)
                    return [{"id": m["id"], "name": m.get("name"), "contextWindow": m.get("contextWindow"), "maxTokens": m.get("maxTokens")} for m in models]
                except Exception:
                    pass
            # network probe for custom baseURL
            base_url_probe = request.get("baseURL") or request.get("base_url") if isinstance(request, dict) else None
            api_key_probe = request.get("apiKey") or request.get("api_key") if isinstance(request, dict) else None
            if base_url_probe:
                try:
                    import json as _js
                    import urllib.request as _ur
                    url = base_url_probe.rstrip("/") + "/models"
                    headers = {}
                    if api_key_probe:
                        headers["Authorization"] = "Bearer {}".format(api_key_probe)
                    req = _ur.Request(url, headers=headers, method="GET")
                    with _ur.urlopen(req, timeout=8) as resp:
                        data = _js.loads(resp.read().decode("utf-8"))
                        items = data.get("data") or data.get("models") or []
                        out = []
                        for it in items:
                            mid = it.get("id") if isinstance(it, dict) else None
                            if isinstance(mid, str) and mid:
                                out.append({"id": mid, "name": it.get("name") or it.get("id")})
                        if out:
                            return out
                except Exception:
                    pass
            return [
                {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)"},
                {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)"},
            ]

        try:
            llm_service.register_model_discovery("llm", _discover)
            llm_service.register_model_discovery("llm-deepseek", _discover)
            llm_service.register_model_discovery("llm-openai", _discover)
        except Exception:
            pass
