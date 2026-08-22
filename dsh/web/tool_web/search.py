import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


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
