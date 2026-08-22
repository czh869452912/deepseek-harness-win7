from typing import Any, Dict, Optional


def format_fetch_output(url: str, content: str, status_code: int = 200, truncated: bool = False) -> str:
    footer = "\n\n(Content truncated. Fetch a more specific URL or section for the full text.)" if truncated else ""
    return f"Fetched {url} (HTTP {status_code}):\n\n{content}{footer}"
