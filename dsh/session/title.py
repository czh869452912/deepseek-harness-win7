"""
Log-backed session title service, normalization, and fallback.
1:1 aligned with official `@deepseek-ai/dsh-session-title`.
"""

import re
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


OSC_SEQUENCE = re.compile(r"(?:\x1b\]|\x9d)(?:(?!\x07|\x1b\\)[\s\S])*(?:\x07|\x1b\\|$)", re.UNICODE)
CSI_SEQUENCE = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]", re.UNICODE)
ESC_SEQUENCE = re.compile(r"\x1b[@-_]", re.UNICODE)
CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", re.UNICODE)
DIRECTIONAL_CONTROL = re.compile(r"[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff]", re.UNICODE)


def normalize_session_title(text: str, max_chars: int = 80) -> str:
    """
    Remove controls, ANSI escape codes, collapse whitespace, and truncate text safely.
    """
    if not text:
        return ""
    clean = OSC_SEQUENCE.sub("", text)
    clean = CSI_SEQUENCE.sub("", clean)
    clean = ESC_SEQUENCE.sub("", clean)
    clean = CONTROL_CHARACTER.sub("", clean)
    clean = DIRECTIONAL_CONTROL.sub("", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:max_chars]


def fallback_session_title(events: List[Dict[str, Any]], max_chars: int = 80) -> Optional[str]:
    """
    Derive fallback title from first non-empty user prompt in session log.
    """
    for ev in events:
        if ev.get("type") == "user/message":
            data = ev.get("data", {})
            content = data.get("content", "")
            if isinstance(content, str) and content.strip():
                return normalize_session_title(content, max_chars=max_chars)
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                        return normalize_session_title(b.get("text", ""), max_chars=max_chars)
    return None


class SessionTitleService:
    """
    Session Title Service mounted at `ctx.sessionTitle`.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx

    def get_title(self, session: Any) -> str:
        events = getattr(session, "events", [])
        for ev in reversed(events):
            if ev.get("type") == "session/title":
                t = ev.get("data", {}).get("title")
                if t:
                    return normalize_session_title(t)
        fallback = fallback_session_title(events)
        return fallback or "Untitled Session"

    def set_title(self, session: Any, title: str) -> Dict[str, Any]:
        norm = normalize_session_title(title)
        return session.append("session/title", {"title": norm, "source": {"kind": "user"}})


class SessionTitlePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-title`: Mounts `ctx.sessionTitle`.
    """

    id = "session-title"
    name = "@deepseek-ai/dsh-session-title"

    def apply(self, ctx: Any) -> None:
        service = SessionTitleService(ctx)
        ctx.set_service("sessionTitle", service)
