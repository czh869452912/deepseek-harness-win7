"""
Durable projection state for dynamic runtime context.
Aligned 1:1 with official `@deepseek-ai/dsh-agent-loop/runtime-context`.
"""

from typing import Any, Dict, List, Optional
from dsh.core.surface import is_replacement_surface_event


SOURCE = "@deepseek-ai/dsh-system-prompt"
CLEARED = "Current runtime context: none. Earlier runtime-context snapshots no longer apply."


def is_owned(message: Dict[str, Any]) -> bool:
    src = message.get("source", {})
    if isinstance(src, dict):
        return src.get("kind") == "plugin" and src.get("plugin") == SOURCE
    return False


def text_of(message: Dict[str, Any]) -> Optional[str]:
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if isinstance(content, list) and len(content) == 1:
        block = content[0]
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text")
    return None


class RuntimeContextProjection:
    """Tracks the last retained runtime-context snapshot without owning its commit."""

    def __init__(self, ctx: Any, session: Any):
        self.session = session
        self.retained: Optional[Dict[str, Any]] = None  # None: not initialized, {"seq": int, "text": str}

        # Initialize from existing session events
        surface_nodes = set(getattr(session.surface, "nodes", []))
        for event in reversed(getattr(session, "events", [])):
            if event.get("type") == "user/message" and is_owned(event.get("data", {})):
                seq = event.get("seq", 0)
                if seq in surface_nodes:
                    self.retained = {"seq": seq, "text": text_of(event.get("data", {}))}
                    break

        if hasattr(ctx, "on"):
            ctx.on("session/event", self._on_session_event)

    def _on_session_event(self, subject: Any, event: Dict[str, Any]) -> None:
        if subject is not None and subject is not self.session:
            return
        ev_type = event.get("type")
        if ev_type == "user/message" and is_owned(event.get("data", {})):
            self.retained = {"seq": event.get("seq", 0), "text": text_of(event.get("data", {}))}
        elif (
            self.retained is not None
            and is_replacement_surface_event(event)
            and self.retained.get("seq") in (event.get("sourceEventSeqs") or [])
        ):
            self.retained = None

    def project(self, current: str, sections: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        """
        Create an uncommitted snapshot only when the retained value differs.
        """
        if self.retained is None and len(current) == 0:
            return None
        snapshot = CLEARED if len(current) == 0 else current
        if self.retained and self.retained.get("text") == snapshot:
            return None

        src: Dict[str, Any] = {"kind": "plugin", "plugin": SOURCE}
        if sections and len(sections) > 0:
            src["form"] = "snapshot"
            src["sections"] = sections
        elif len(current) > 0:
            src["form"] = "snapshot"
            src["sections"] = []

        return {
            "role": "user",
            "content": [{"type": "text", "text": snapshot}],
            "source": src,
        }

