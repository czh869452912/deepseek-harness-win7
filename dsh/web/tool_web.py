import asyncio
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.web.web_service import WebService


class ToolWebPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-web`: Exposes web_search and web_fetch model tools.
    """

    id = "tool-web"
    name = "@deepseek-ai/dsh-tool-web"
    inject = ["tools", "web"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.enable_search = bool(self.config.get("search", True))
        self.enable_fetch = bool(self.config.get("fetch", True))
        self.max_results = int(self.config.get("searchMaxResults", 10))
        self.max_output_chars = int(self.config.get("fetchMaxOutputChars", 200000))

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        web = ctx.get("web")
        if not tools or not web:
            return

        disposers = []

        if self.enable_search:
            async def exec_web_search(query: str) -> str:
                try:
                    results = await web.search(query, max_results=self.max_results)
                    if not results:
                        return f"No search results found for '{query}'."
                    lines = [f"Search results for '{query}':"]
                    for idx, r in enumerate(results, 1):
                        lines.append(f"\n[{idx}] {r.get('title', 'Untitled')}")
                        lines.append(f"URL: {r.get('url', '')}")
                        lines.append(f"{r.get('snippet', '')}")
                    return "\n".join(lines)
                except Exception as e:
                    return f"Error executing web_search: {e}"

            d1 = tools.register_tool({
                "name": "web_search",
                "description": "Perform web search to find current information and documentation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query string"},
                    },
                    "required": ["query"],
                },
                "execute": exec_web_search,
            })
            disposers.append(d1)

        if self.enable_fetch:
            async def exec_web_fetch(url: str) -> str:
                try:
                    res = await web.fetch(url)
                    content = res.get("content", "")
                    if len(content) > self.max_output_chars:
                        content = content[: self.max_output_chars] + "\n\n(Content clipped to max output limit)"
                    return f"Content from {url}:\n\n{content}"
                except Exception as e:
                    return f"Error fetching {url}: {e}"

            d2 = tools.register_tool({
                "name": "web_fetch",
                "description": "Fetch content from a URL and extract its text/markdown representation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target HTTP/HTTPS URL"},
                    },
                    "required": ["url"],
                },
                "execute": exec_web_fetch,
            })
            disposers.append(d2)

        def cleanup():
            for d in disposers:
                d()

        ctx.effect(cleanup)
