from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class PersonaPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-persona`: Sets agent system prompt persona.
    """

    id = "persona"
    name = "@deepseek-ai/dsh-persona"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.text = self.config.get("text", "You are a helpful software engineer assistant.")

    def apply(self, ctx: Any) -> None:
        ctx.set_service("persona", self)

    def get_prompt(self) -> str:
        return self.text
