import asyncio
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from dsh.cordis.plugin import Plugin
from dsh.web.web_service import WebService


def source_label(url: str, title: Optional[str] = None) -> str:
    if title and title.strip():
        return title.strip()
    try:
        parsed = urlparse(url)
        return parsed.hostname or url
    except Exception:
        return url


def format_search_output(
    sources: List[Dict[str, Any]],
    content: Optional[str] = None,
    truncated: bool = False,
) -> str:
    parts: List[str] = []
    if content and content.strip():
        parts.append(content.strip())

    if sources:
        lines: List[str] = []
        for src in sources:
            url = src.get("url", "")
            title = src.get("title")
            label = source_label(url, title)
            meta: List[str] = []
            snippet = src.get("snippet")
            published_at = src.get("publishedAt") or src.get("published_at")
            if snippet:
                meta.append(str(snippet))
            if published_at:
                meta.append(f"({published_at})")
            suffix = f" — {' '.join(meta)}" if meta else ""
            lines.append(f"- [{label}]({url}){suffix}")
        parts.append("Sources:\n" + "\n".join(lines))
    elif not content:
        parts.append("No results found.")

    if truncated:
        parts.append(f"(Showing the first {len(sources)} sources. Refine the query for more.)")

    parts.append("Cite the relevant URLs above as markdown links in your answer.")
    return "\n\n".join(parts)


class ToolWebPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-web`: Exposes official `web_search` and `web_fetch` model tools.
    Supports multi-query parallel execution, deduplication, and formatted markdown results.
    """

    id = "tool-web"
    name = "@deepseek-ai/dsh-tool-web"
    inject = ["tools", "web"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.enable_search = bool(cfg.get("search", True))
        self.enable_fetch = bool(cfg.get("fetch", True))
        self.max_results = int(cfg.get("searchMaxResults", 8))
        self.max_queries = int(cfg.get("searchMaxQueries", 4))
        self.max_output_chars = int(cfg.get("fetchMaxOutputChars", 200000))
        self.search_timeout_ms = int(cfg.get("searchTimeoutMs", 60000))

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        web: WebService = ctx.get("web")
        if not tools or not web:
            return

        disposers = []

        if self.enable_search:
            async def exec_web_search(
                queries: Optional[List[str]] = None,
                query: Optional[str] = None,
            ) -> str:
                query_list: List[str] = []
                if queries:
                    if isinstance(queries, list):
                        query_list = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
                    elif isinstance(queries, str) and queries.strip():
                        query_list = [queries.strip()]
                elif query and isinstance(query, str) and query.strip():
                    query_list = [query.strip()]

                if not query_list:
                    return "Error: queries must contain at least one non-empty query string."

                if len(query_list) > self.max_queries:
                    noun = "query" if self.max_queries == 1 else "queries"
                    return f"Error: queries must contain at most {self.max_queries} {noun}"

                unique_queries = list(dict.fromkeys(query_list))

                async def fetch_one_query(q: str) -> List[Dict[str, Any]]:
                    try:
                        return await web.search(q, max_results=self.max_results, timeout_ms=self.search_timeout_ms)
                    except Exception:
                        return []

                raw_results = await asyncio.gather(*[fetch_one_query(q) for q in unique_queries])

                seen_urls = set()
                merged_sources: List[Dict[str, Any]] = []
                max_rank = max((len(r) for r in raw_results), default=0)
                truncated = False

                for rank in range(max_rank):
                    for r_list in raw_results:
                        if rank < len(r_list):
                            src = r_list[rank]
                            url = src.get("url", "")
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                if len(merged_sources) >= self.max_results:
                                    truncated = True
                                    break
                                merged_sources.append(src)
                    if len(merged_sources) >= self.max_results:
                        break

                return format_search_output(merged_sources, content=None, truncated=truncated)

            d1 = tools.register_tool({
                "name": "web_search",
                "description": f"Search the web for current information. Provide 1–{self.max_queries} queries in the required queries array. Returns a list of source URLs and snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Required search queries; accepts 1–{self.max_queries} items and merges their results.",
                        },
                    },
                    "required": ["queries"],
                },
                "execute": exec_web_search,
            })
            disposers.append(d1)

        if self.enable_fetch:
            async def exec_web_fetch(url: str) -> str:
                if not url or not url.strip():
                    return "Error: url must be a non-empty string"
                try:
                    res = await web.fetch(url, timeout_ms=30000)
                    content = res.get("content", "")
                    truncated = False
                    if len(content) > self.max_output_chars:
                        content = content[: self.max_output_chars]
                        truncated = True
                    footer = "\n\n(Content truncated. Fetch a more specific URL or section for the full text.)" if truncated else ""
                    return f"Fetched {url} (HTTP 200):\n\n{content}{footer}"
                except Exception as e:
                    return f"Error fetching {url}: {e}"

            d2 = tools.register_tool({
                "name": "web_fetch",
                "description": "Fetch content from a URL and extract its text/markdown representation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to fetch. Must be a valid HTTP/HTTPS URL."},
                    },
                    "required": ["url"],
                },
                "execute": exec_web_fetch,
            })
            disposers.append(d2)

        def cleanup():
            for d in disposers:
                if callable(d):
                    d()

        ctx.effect(cleanup)


