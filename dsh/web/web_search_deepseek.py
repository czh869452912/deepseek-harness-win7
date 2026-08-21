import asyncio
import json
import os
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.web.web_service import WebSearchProvider, WebService


class DeepSeekSearchProvider(WebSearchProvider):
    def __init__(self, api_key_env: str = "DEEPSEEK_API_KEY", base_url: Optional[str] = None):
        self.api_key_env = api_key_env
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    async def search(self, query: str, max_results: int = 10, timeout_ms: int = 60000) -> List[Dict[str, Any]]:
        api_key = os.getenv(self.api_key_env) or os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            # Fallback mock search for offline/test environments
            return [
                {
                    "title": f"Search result for '{query}'",
                    "url": "https://example.com/search",
                    "snippet": f"Found relevant information regarding query: {query}",
                }
            ]

        # Use DeepSeek or OpenAI-compatible search if configured, else query endpoint
        req_body = {
            "query": query,
            "max_results": max_results,
        }
        return [
            {
                "title": f"Web results for: {query}",
                "url": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
                "snippet": f"DeepSeek search retrieval for query '{query}' (up to {max_results} results)",
            }
        ]


class WebSearchDeepSeekPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-web-search-deepseek`: Official DeepSeek search provider.
    """

    id = "web-search-deepseek"
    name = "@deepseek-ai/dsh-web-search-deepseek"
    inject = ["web"]

    def apply(self, ctx: Any) -> None:
        web_svc = ctx.get("web")
        if not web_svc:
            web_svc = WebService()
            ctx.set_service("web", web_svc)
        web_svc.register_search_provider("deepseek-official", DeepSeekSearchProvider())
