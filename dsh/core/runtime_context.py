"""
Durable projection state for dynamic runtime context.
Aligned 1:1 with official `@deepseek-ai/dsh-agent-loop/runtime-context`.
"""

from typing import Any, Dict, List, Optional
from dsh.core.surface import is_replacement_surface_event


SOURCE = "@deepseek-ai/dsh-system-prompt"
CLEARED = "Current runtime context: none. Earlier runtime-context snapshots no longer apply."
_UNSET = object()


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
        # Match TypeScript's `undefined` (never observed) versus `null` (known
        # to have no retained snapshot).  Callers inspect ``retained`` for the
        # durable state, so keep the sentinel private and expose None only for
        # the initialized-empty state.
        self._retained_state: Any = _UNSET

        # Initialize from existing session events
        surface_nodes = set(getattr(session.surface, "nodes", []))
        for event in reversed(getattr(session, "events", [])):
            if event.get("type") == "user/message" and is_owned(event.get("data", {})):
                seq = event.get("seq", 0)
                if seq in surface_nodes:
                    self._retained_state = {"seq": seq, "text": text_of(event.get("data", {}))}
                    break
                # An owned snapshot exists in history but is no longer on the
                # authoritative surface.  Initialization is therefore known
                # empty, not uninitialized.
                if self._retained_state is _UNSET:
                    self._retained_state = None

        if hasattr(ctx, "on"):
            ctx.on("session/event", self._on_session_event)

    def _on_session_event(self, subject: Any, event: Dict[str, Any]) -> None:
        if subject is not None and subject is not self.session:
            return
        ev_type = event.get("type")
        if ev_type == "user/message" and is_owned(event.get("data", {})):
            self._retained_state = {"seq": event.get("seq", 0), "text": text_of(event.get("data", {}))}
        elif (
            isinstance(self._retained_state, dict)
            and is_replacement_surface_event(event)
            and self._retained_state.get("seq") in (event.get("sourceEventSeqs") or [])
        ):
            self._retained_state = None

    @property
    def retained(self) -> Optional[Dict[str, Any]]:
        """Current retained snapshot, or None when the surface has none."""
        return self._retained_state if isinstance(self._retained_state, dict) else None

    def project(self, current: str, sections: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        """
        Create an uncommitted snapshot only when the retained value differs.
        """
        if self._retained_state is _UNSET and len(current) == 0:
            return None
        snapshot = CLEARED if len(current) == 0 else current
        if isinstance(self._retained_state, dict) and self._retained_state.get("text") == snapshot:
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

