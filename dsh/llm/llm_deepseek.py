"""Native DeepSeek provider registration; request facts are resolved per call."""
import copy
import logging

from dsh.cordis.plugin import Plugin
from dsh.llm.llm_service import LLMService, LlmError, assert_usable_api_key
from dsh.llm.deepseek_config import resolve_options
from dsh.cordis.environment import launch_environment_of
from dsh.settings.provider import install_settings_section, deep_equal_json


class DeepSeekAdapter:
    def __init__(self, ctx, config):
        self.ctx, self.config = ctx, copy.deepcopy(config)
        self.source = lambda: self.config
        self.last_raw, self.last_good = None, None
        self.files = None
        self.user_id = None
        self.options()

    def options(self):
        raw = self.source()
        if self.last_good is None or not deep_equal_json(raw, self.last_raw):
            try:
                resolved = resolve_options(raw, launch_environment_of(self.ctx))
            except (ValueError, TypeError) as error:
                if self.last_good is None:
                    raise
                logging.getLogger("llm-deepseek").error("Keeping the last good configuration: %s", error)
            else:
                self.last_good = resolved
            self.last_raw = copy.deepcopy(raw)
        return copy.deepcopy(self.last_good)

    def provider_info(self, provider):
        return {"id": provider, "name": "DeepSeek"}

    def provider_retry_policy(self, provider):
        return self.options()["retryPolicy"]

    def image_request_pricing(self, provider, model):
        from dsh.llm.deepseek_image_pricing import request_pricing
        def access(ref):
            attachments, fs = self.ctx.get("attachments"), self.ctx.get("fs")
            location = getattr(attachments, "imageHostPath", None)
            mapping = getattr(fs, "processPathFromHostPath", None)
            path = location(ref) if location else None
            return mapping(path) if mapping and path is not None else None
        return request_pricing(self.options(), model, access)

    imageRequestPricing = image_request_pricing

    async def list_models(self, provider):
        options = self.options()
        return [self.catalog_info(provider, model) for model in options['models']]

    @staticmethod
    def catalog_info(provider, model):
        info = dict(provider=provider, id=model['id'], name=model.get('name', model['id']),
                    inputModalities=copy.deepcopy(model.get('inputModalities', ['text'])))
        if 'description' in model:
            info['description'] = model['description']
        return info

    async def resolve_model(self, provider, model, signal=None):
        options = self.options()
        return self.model_info(options, provider, model)

    @staticmethod
    def model_info(options, provider, model):
        configured = next((row for row in options['models'] if row['id'] == model), {'id': model})
        info = DeepSeekAdapter.catalog_info(provider, configured)
        info['context'] = {'contextWindow': configured.get('contextWindow', options['defaultContextWindow'])}
        info["defaultMaxTokens"] = configured.get("maxTokens", options["maxTokens"])
        efforts = [dict(id=key, name=name, description=description) for key, name, description in (
            ('off', 'Off', 'Use for simple tasks that do not need reasoning.'),
            ('low', 'Low', 'Prefer for routine or latency-sensitive tasks.'),
            ('high', 'High', 'The default balance for most tasks.'),
            ('max', 'Max', 'Reserve for the hardest quality-first tasks.'))]
        info["reasoning"] = {"efforts": efforts[:1] if options.get("thinking") == "disabled" else efforts,
                             "defaultEffort": options.get("reasoningEffort", "off" if options.get("thinking") == "disabled" else "high")}
        return info

    def stream(self, request):
        return self.stream_with_options(request, self.options())

    async def prepare_call(self, provider, model, signal=None):
        options = self.options()
        return {"model": self.model_info(options, provider, model),
                "retryPolicy": copy.deepcopy(options["retryPolicy"]),
                "stream": lambda request: self.stream_with_options(request, options)}

    def stream_with_options(self, request, options):
        from dsh.llm.image_content import images
        has_images = any(any(images(message.get("content"))) for message in request["messages"])
        if has_images:
            model = next((row for row in options["models"] if row["id"] == request["model"]), {})
            if "image" not in model.get("inputModalities", []):
                raise LlmError("This DeepSeek model does not accept image input", "UNSUPPORTED_CONTENT")
            if self.ctx.get("attachments") is None:
                raise LlmError("DeepSeek image conversion requires the durable attachment service", "UNSUPPORTED_CONTENT")
        ref = options.get("apiKeyEnv", "DEEPSEEK_API_KEY")
        credentials = self.ctx.get("credentials")
        hit = credentials.resolve(ref) if credentials is not None else None
        value = hit.get("value") if isinstance(hit, dict) else getattr(hit, "value", None)
        environment = launch_environment_of(self.ctx)
        ambient = environment.get(ref)
        if value is None and credentials is None:
            value = ambient.get("value") if isinstance(ambient, dict) else getattr(ambient, "value", None)
        if not value:
            raise LlmError("No API key for deepseek-official; configure {} in credentials or the launch environment".format(ref), "MISSING_CREDENTIAL")
        base_url = options["baseURL"]
        transport = LLMService(api_key=assert_usable_api_key(value, "llm-deepseek", ref), base_url=base_url)
        resolved = dict(request)
        resolved.setdefault("provider", "deepseek-official")
        resolved.setdefault("reasoningEffort", options.get("reasoningEffort", "off" if options.get("thinking") == "disabled" else "high"))
        resolved.setdefault("maxTokens", self.model_info(options, resolved["provider"], resolved["model"])["defaultMaxTokens"])
        resolved["streamIdleTimeoutMs"] = options["streamIdleTimeoutMs"]
        from dsh.identity.anonymous_user_id import get_or_create_anonymous_user_id
        if self.user_id is None:
            self.user_id = get_or_create_anonymous_user_id()
        resolved["_provider_headers"] = {"x-deepseek-harness-user-id": str(self.user_id)}
        if resolved.get("sessionId") is not None:
            resolved["_provider_headers"]["x-deepseek-harness-session-id"] = str(resolved["sessionId"])
        if resolved.get("purpose") == "compaction":
            resolved["_provider_headers"]["x-deepseek-harness-compact"] = "1"
        if options.get("thinking") == "disabled" and resolved["reasoningEffort"] != "off":
            raise LlmError("This DeepSeek deployment disables thinking", "UNSUPPORTED_REASONING_EFFORT")
        if self.ctx.get("deepseekLlmApiExtensions") is not None or has_images:
            from dsh.llm.deepseek_request import request_stream
            return request_stream(self, transport, resolved, options)
        from dsh.llm.stream_bridge import OwnedStream
        return OwnedStream(lambda signal: transport._default_chat_completion_stream(
            resolved["messages"], tools=resolved.get("tools"), model=resolved["model"],
            system=resolved.get("system"), temperature=resolved.get("temperature"), options=dict(resolved, signal=signal)), resolved.get("signal"))

    async def close(self):
        if self.files is not None:
            await self.files.close()



class LLMDeepSeekPlugin(Plugin):
    id = "llm-deepseek"
    inject = ["llm"]

    def apply(self, ctx):
        llm = ctx.get("llm")
        adapter = DeepSeekAdapter(ctx, self.config)
        ctx.effect(lambda: adapter.close, "DeepSeek upload teardown")
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
        registered_policy = [adapter.provider_retry_policy("deepseek-official")]

        def changed():
            policy = adapter.provider_retry_policy("deepseek-official")
            if policy != registered_policy[0]:
                dispose_route.replace(["deepseek-official"])
                registered_policy[0] = policy

        from dsh.llm.deepseek_schema import config_schema
        install_settings_section(ctx, "llm-deepseek", config_schema(), self.config, {
            "setSource": lambda source: setattr(adapter, "source", source), "onChange": changed,
            "validate": lambda raw: resolve_options(raw, launch_environment_of(ctx)),
        })
