from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.services.llm import LLMService


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

        llm_service = LLMService(api_key=api_key, base_url=base_url, model=model)
        ctx.set_service("llm", llm_service)
