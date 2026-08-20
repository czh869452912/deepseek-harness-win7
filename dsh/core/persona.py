import os
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class PersonaPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-persona`: Sets agent system prompt persona.
    Supports complete=True to isolate the prompt as the sole system prompt.
    """

    id = "persona"
    name = "@deepseek-ai/dsh-persona"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.text = self.config.get("text", "You are a helpful software engineer assistant.")
        self.complete = bool(self.config.get("complete", False))
        self.include_runtime_context = bool(self.config.get("includeRuntimeContext", not self.complete))

    def apply(self, ctx: Any) -> None:
        ctx.set_service("persona", self)

        # Interpolate variables like {{cwd}} and {{model}} if present
        def resolve_persona_text() -> str:
            model_name = getattr(ctx.get("llm"), "model", "deepseek-chat")
            cwd = os.getcwd()
            resolved = self.text.replace("{{cwd}}", cwd).replace("{{model}}", str(model_name))
            return resolved

        self._resolved_getter = resolve_persona_text

        # If complete is True, intercept waterfall and guarantee exclusive prompt
        if self.complete:
            def complete_prompt_interceptor(prompt: Any, *args: Any, **kwargs: Any) -> str:
                return resolve_persona_text()

            ctx.on("agent/prompt-assemble", complete_prompt_interceptor, prepend=False)

    def get_prompt(self) -> str:
        if hasattr(self, "_resolved_getter"):
            return self._resolved_getter()
        return self.text
