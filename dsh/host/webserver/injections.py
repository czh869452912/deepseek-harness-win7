"""
Structured index injections (`@deepseek-ai/dsh-host-webserver/injections`).
Typed injection rows contributed by Cordis plugins to index.html boot markup.
Aligned 1:1 with reference `injections.ts`.
"""

import json
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

IndexInjectionPlacement = Literal["head", "body"]


def escape_html_attribute(value: str) -> str:
    """Escape a row value before placing it in a quoted HTML attribute."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_row(row: Dict[str, Any]) -> Tuple[IndexInjectionPlacement, str]:
    """Render one injection row to markup with its target placement."""
    kind = row.get("kind")
    if kind == "global":
        name_str = json.dumps(row.get("name", "")).replace("<", "\\u003c")
        val = row.get("value")
        val_str = "undefined" if val is None else json.dumps(val, ensure_ascii=False).replace("<", "\\u003c")
        return "head", f"<script>globalThis[{name_str}] = {val_str}</script>"

    elif kind == "script":
        placement: IndexInjectionPlacement = row.get("placement", "head")
        text = row.get("text", "")
        return placement, f"<script>{text}</script>"

    elif kind == "script-src":
        placement: IndexInjectionPlacement = row.get("placement", "head")
        src = escape_html_attribute(row.get("src", ""))
        return placement, f'<script src="{src}"></script>'

    elif kind == "style":
        text = row.get("text", "")
        return "head", f"<style>{text}</style>"

    elif kind == "html":
        placement: IndexInjectionPlacement = row.get("placement", "head")
        html_text = row.get("html", "")
        return placement, html_text

    raise ValueError(f"webserver: unknown index injection row {row}")


def render_index_injections(html: str, rows: List[Dict[str, Any]]) -> str:
    """
    Render injection rows into an index.html body:
    Head rows inserted after opening <head>, body rows inserted after opening <body>.
    """
    head_markup = []
    body_markup = []

    for r in rows:
        placement, markup = render_row(r)
        if placement == "head":
            head_markup.append(markup)
        else:
            body_markup.append(markup)

    head_str = "".join(head_markup)
    body_str = "".join(body_markup)

    out = html
    if head_str:
        m = re.search(r"<head(?:\s[^>]*)?>", out, re.IGNORECASE)
        if m:
            idx = m.end()
            out = out[:idx] + head_str + out[idx:]
        else:
            out = head_str + out

    if body_str:
        m = re.search(r"<body(?:\s[^>]*)?>", out, re.IGNORECASE)
        if m:
            idx = m.end()
            out = out[:idx] + body_str + out[idx:]
        else:
            out = out + body_str

    return out
