import asyncio
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.web.web_service import WebFetchProvider, WebService


class HTMLToMarkdownParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.in_script = False
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.in_script = True
        elif tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.in_script = False
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self.text_parts.append("\n")

    def handle_data(self, data):
        if not self.in_script and not self.in_style:
            self.text_parts.append(data)

    def get_markdown(self) -> str:
        raw = "".join(self.text_parts)
        # Normalize consecutive whitespaces and newlines
        cleaned = re.sub(r"\n\s*\n", "\n\n", raw)
        return cleaned.strip()


class HttpFetchProvider(WebFetchProvider):
    async def fetch(self, url: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        timeout_sec = min(120, max(1, timeout_ms / 1000.0))
        headers = {"User-Agent": "DeepSeek-Harness/0.1.0"}

        def do_request():
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                status = resp.status
                content_type = resp.headers.get("Content-Type", "")
                raw_bytes = resp.read(500000)  # max 500KB download
                text = raw_bytes.decode("utf-8", errors="replace")
                return status, content_type, text

        loop = asyncio.get_running_loop()
        status, content_type, text = await loop.run_in_executor(None, do_request)

        if "html" in content_type.lower():
            parser = HTMLToMarkdownParser()
            parser.feed(text)
            markdown = parser.get_markdown()
        else:
            markdown = text

        return {
            "url": url,
            "status": status,
            "content": markdown,
        }


class WebFetchHttpPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-web-fetch-http`: HTML fetch & conversion provider.
    """

    id = "web-fetch-http"
    name = "@deepseek-ai/dsh-web-fetch-http"
    inject = ["web"]

    def apply(self, ctx: Any) -> None:
        web_svc = ctx.get("web")
        if not web_svc:
            web_svc = WebService()
            ctx.set_service("web", web_svc)
        web_svc.register_fetch_provider("http", HttpFetchProvider())
