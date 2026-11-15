"""
Log-backed session title service, normalization, and fallback.
1:1 aligned with official `@deepseek-ai/dsh-session-title`.
"""

import re
import math
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin


OSC_SEQUENCE = re.compile(r"(?:\x1b\]|\x9d)(?:(?!\x07|\x1b\\)[\s\S])*(?:\x07|\x1b\\|$)", re.UNICODE)
CSI_SEQUENCE = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]", re.UNICODE)
ESC_SEQUENCE = re.compile(r"\x1b[@-_]", re.UNICODE)
CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", re.UNICODE)
DIRECTIONAL_CONTROL = re.compile(r"[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff]", re.UNICODE)


def _positive_integer(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0 and int(value) == value


def _title_characters(text):
    index = 0
    while index < len(text):
        char = text[index];index += 1
        if 0xd800 <= ord(char) <= 0xdbff and index < len(text) and 0xdc00 <= ord(text[index]) <= 0xdfff:
            char = chr(0x10000 + ((ord(char) - 0xd800) << 10) + ord(text[index]) - 0xdc00);index += 1
        yield char


def _title_character_bytes(char):
    # Node's UTF-8 encoder counts an unpaired UTF-16 surrogate as U+FFFD.
    return 3 if 0xd800 <= ord(char) <= 0xdfff else len(char.encode('utf-8'))


def truncate_title_utf8(input_text: str, max_bytes: int) -> str:
    """
    Truncate a string to a UTF-8 byte budget without splitting a Unicode code point.
    """
    if not _positive_integer(max_bytes):
        raise ValueError("maxBytes must be a positive integer")
    if sum(_title_character_bytes(char) for char in _title_characters(input_text)) <= max_bytes:
        return input_text
    output = ""
    used = 0
    for ch in _title_characters(input_text):
        ch_bytes = _title_character_bytes(ch)
        if used + ch_bytes > max_bytes:
            break
        output += ch
        used += ch_bytes
    return output


def clean_title_text(input_text: str) -> str:
    """Remove controls and produce one trimmed, whitespace-normalized line."""
    clean = OSC_SEQUENCE.sub("", input_text)
    clean = CSI_SEQUENCE.sub("", clean)
    clean = ESC_SEQUENCE.sub("", clean)
    clean = CONTROL_CHARACTER.sub("", clean)
    clean = DIRECTIONAL_CONTROL.sub("", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def normalize_session_title(input_text: str, max_bytes: int = 80) -> str:
    """
    Normalize one accepted session title and enforce its UTF-8 byte budget.
    """
    if not _positive_integer(max_bytes):
        raise ValueError("maxBytes must be a positive integer")
    if not input_text:
        return ""
    return truncate_title_utf8(clean_title_text(input_text), max_bytes).rstrip()


def fallback_session_title(
    source: Union[str, List[Dict[str, Any]]],
    max_words: int = 5,
    max_bytes: int = 40,
) -> str:
    """
    Derive the deterministic first-prompt fallback.
    """
    if not _positive_integer(max_words):
        raise ValueError("maxWords must be a positive integer")
    if not _positive_integer(max_bytes):
        raise ValueError("maxBytes must be a positive integer")

    if isinstance(source, list):
        for ev in source:
            if ev.get("type") == "user/message":
                data = ev.get("data", {})
                content = data.get("content", "")
                if isinstance(content, str) and content.strip():
                    return fallback_session_title(content, max_words=max_words, max_bytes=max_bytes)
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                            return fallback_session_title(b.get("text", ""), max_words=max_words, max_bytes=max_bytes)
        return ""

    words = [w for w in clean_title_text(source).split(" ") if w][:int(max_words)]
    return truncate_title_utf8(" ".join(words), max_bytes).rstrip()


def fold_session_title(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Fold the latest logged title without consulting mutable metadata.
    """
    for ev in reversed(events):
        if ev.get("type") == "session/title":
            data = ev.get("data", {})
            return {
                "title": data.get("title", ""),
                "messageSeqs": list(data.get("messageSeqs", [])),
                "source": data.get("source", {"kind": "fallback"}),
                "eventSeq": ev.get("seq", 0),
                "updatedAt": ev.get("time", 0),
            }
    return None


def collect_session_title_messages(
    events: List[Dict[str, Any]],
    through_seq: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Collect human text-bearing user messages in log order.
    """
    messages: List[Dict[str, Any]] = []
    for ev in events:
        if through_seq is not None and ev.get("seq", 0) > through_seq:
            break
        if ev.get("type") != "user/message":
            continue
        data = ev.get("data", {})
        src = data.get("source", {})
        if not isinstance(src, dict) or src.get("kind") != "user":
            continue
        content = data.get("content", [])
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        else:
            text = ""
        if len(normalize_session_title(text, max_bytes=1000000)) == 0:
            continue
        messages.append({"seq": ev.get("seq", 0), "text": text})
    return messages


class SessionTitleService:
    """
    Session Title Service mounted at `ctx.sessionTitle`.
    """

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        cfg = config or {}
        self.fallback_max_words = cfg.get("fallbackMaxWords", 5)
        self.fallback_max_bytes = cfg.get("fallbackMaxBytes", 40)
        self.max_title_bytes = cfg.get("maxTitleBytes", 80)

        if ctx:
            ctx.on("session/event", self._on_session_event)

    def get(self, session: Any) -> Optional[Dict[str, Any]]:
        events = getattr(session, "events", [])
        folded = fold_session_title(events)
        if folded is not None:
            return folded
        messages = collect_session_title_messages(events)
        if not messages:
            return None
        first = messages[0]
        title = fallback_session_title(first["text"], max_words=self.fallback_max_words, max_bytes=self.fallback_max_bytes)
        if not title:
            return None
        first_ev = next((e for e in events if e.get("seq") == first["seq"]), None)
        t = first_ev.get("time", 0) if first_ev else 0
        return {
            "title": title,
            "messageSeqs": [first["seq"]],
            "source": {"kind": "fallback"},
            "eventSeq": -1,
            "updatedAt": t,
        }

    def get_title(self, session: Any) -> str:
        snap = self.get(session)
        if snap and snap.get("title"):
            return snap["title"]
        fallback = fallback_session_title(getattr(session, "events", []), max_words=self.fallback_max_words, max_bytes=self.fallback_max_bytes)
        return fallback or "Untitled Session"

    def set_title(self, session: Any, title: str) -> Dict[str, Any]:
        return self.rename(session, title)

    def rename(self, session: Any, title: str) -> Dict[str, Any]:
        norm = normalize_session_title(title, max_bytes=self.max_title_bytes)
        if not norm:
            raise ValueError("session title must contain visible characters")
        return session.append(
            "session/title",
            {
                "title": norm,
                "messageSeqs": [],
                "source": {"kind": "user"},
            },
        )

    def _on_session_event(self, session: Any, event: Dict[str, Any]) -> None:
        if event.get("type") != "user/message":
            return
        events = getattr(session, "events", [])
        if fold_session_title(events) is not None:
            return
        messages = collect_session_title_messages(events)
        if not messages:
            return
        first = messages[0]
        title = fallback_session_title(first["text"], max_words=self.fallback_max_words, max_bytes=self.fallback_max_bytes)
        if title:
            def _do_append():
                if fold_session_title(session.events) is None:
                    session.append(
                        "session/title",
                        {
                            "title": title,
                            "messageSeqs": [first["seq"]],
                            "source": {"kind": "fallback"},
                        },
                    )

            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.call_soon(_do_append)
            except RuntimeError:
                pass


class SessionTitlePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-title`: Mounts `ctx.sessionTitle`.
    """

    id = "session-title"
    name = "@deepseek-ai/dsh-session-title"
    inject = []

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def apply(self, ctx: Any) -> None:
        service = SessionTitleService(ctx, self.config)
        ctx.set_service("sessionTitle", service)

