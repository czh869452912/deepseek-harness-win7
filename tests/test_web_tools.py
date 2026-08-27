import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.web.web_service import WebService, WebSearchProvider, WebFetchProvider
from dsh.web.web_fetch_http import HTMLToMarkdownParser
from dsh.web.tool_web import ToolWebPlugin


class PromptService:
    def section(self, *args, **kwargs):
        return lambda: None


class MockSearchProvider(WebSearchProvider):
    async def search(self, query: str, max_results: int = 10, timeout_ms: int = 60000):
        return [
            {"title": f"Doc for {query}", "url": "https://example.org/doc", "snippet": "Sample text"}
        ]


class MockFetchProvider(WebFetchProvider):
    async def fetch(self, url: str, timeout_ms: int = 30000):
        return {
            "url": url,
            "status": 200,
            "content": "# Extracted Heading\n\nExtracted body markdown content.",
        }


def test_html_to_markdown_parser():
    html = "<html><body><h1>Title</h1><p>Hello <b>World</b></p><script>console.log(1)</script></body></html>"
    parser = HTMLToMarkdownParser()
    parser.feed(html)
    md = parser.get_markdown()
    assert "Title" in md
    assert "Hello World" in md
    assert "console.log" not in md


@pytest.mark.asyncio
async def test_tool_web_search_and_fetch():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))

    web_svc = WebService()
    web_svc.register_search_provider("mock", MockSearchProvider())
    web_svc.register_fetch_provider("mock", MockFetchProvider())
    ctx.set_service("web", web_svc)
    ctx.set_service("systemPrompt", PromptService())

    fiber = ctx.registry.plugin(ToolWebPlugin, parent_ctx=ctx)
    await fiber
    tools = ctx.get("tools")
    try:
        # 1. Single query uses the required upstream array parameter.
        search_res = await tools.execute_tool("web_search", {"queries": ["python cordis"]})
        assert "Doc for python cordis" in search_res
        assert "https://example.org/doc" in search_res
        assert "Cite the relevant URLs above" in search_res

        # 2. Multi-query official array parameter
        multi_res = await tools.execute_tool("web_search", {"queries": ["python cordis", "asyncio loop"]})
        assert "https://example.org/doc" in multi_res
        assert "Cite the relevant URLs above" in multi_res

        # 3. Web fetch
        fetch_res = await tools.execute_tool("web_fetch", {"url": "https://example.org/article"})
        assert "Extracted Heading" in fetch_res
    finally:
        await fiber.dispose()

