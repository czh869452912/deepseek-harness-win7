"""System prompt registry service used by Cordis prompt-aware plugins."""

from typing import Any, Callable, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class SystemPromptService(Service):
    """Small Cordis-compatible prompt registry with reversible contributions."""

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        self._sections: Dict[str, Any] = {}
        self._tools: List[Callable[[Any], Any]] = []
        super().__init__(ctx, "systemPrompt")
        self.section({"name": "harness:identity", "order": -100,
                      "text": "You are an AI agent powered by DeepSeek Harness."})
        self.section({"name": "deployment:persona", "order": 0,
                      "text": (config or {}).get("persona", "")})

    def section(self, section: Any = None, *args: Any, **kwargs: Any) -> Callable[[], None]:
        name = kwargs.get("name")
        order = kwargs.get("order")
        text = kwargs.get("text")
        if isinstance(section, str):
            if args:
                text = args[0]
            section = {"name": section, "order": order or 0, "text": text or ""}
        elif name is not None:
            section = {"name": name, "order": order or 0, "text": text or ""}
        value = dict(section)
        name = value["name"]
        if name in self._sections:
            raise ValueError('prompt section "%s" is already registered' % name)
        self._sections[name] = value

        def dispose() -> None:
            if self._sections.get(name) is value:
                self._sections.pop(name, None)
        return self.ctx.effect(lambda: dispose, label="systemPrompt.section()")

    def tools(self, provider: Callable[[Any], Any]) -> Callable[[], None]:
        self._tools.append(provider)

        def dispose() -> None:
            try:
                self._tools.remove(provider)
            except ValueError:
                pass
        return self.ctx.effect(lambda: dispose, label="systemPrompt.tools()")

    async def assemble(self, scope: Any = None, signal: Any = None) -> Dict[str, Any]:
        sections = sorted(self._sections.values(), key=lambda item: item.get("order", 0))
        return {"sections": [{"name": item["name"], "text": item.get("text", "")}
                              for item in sections],
                "contexts": [], "tools": [], "variables": {}}


class SystemPromptPlugin(Plugin):
    id = "system-prompt"
    name = "@deepseek-ai/dsh-system-prompt"

    def apply(self, ctx: Any) -> None:
        SystemPromptService(ctx, self.config)
