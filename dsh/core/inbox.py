"""
Incremental projection of durable agent inbox events.
1:1 aligned with official `@deepseek-ai/dsh-agent/inbox`.
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple, Union


class Inbox:
    """
    Incremental projection of durable agent inbox events (`agent/inbox/spliced`).
    Manages next_turn (future turns) and next_step (mid-turn steering / injected context).
    """

    def __init__(
        self,
        session: Optional[Any] = None,
        ctx: Optional[Any] = None,
        agent: Optional[Any] = None,
    ):
        self.agent = agent
        self.session = session or (agent.session if agent and hasattr(agent, "session") else None)
        self.ctx = ctx or (agent.ctx if agent and hasattr(agent, "ctx") else None)
        self._state: Dict[str, List[Dict[str, Any]]] = {
            "next-turn": [],
            "next-step": [],
        }

        # Replay past durable inbox splices from session events if session exists
        if self.session and hasattr(self.session, "events"):
            seed_len = 0
            if hasattr(self.session, "header") and getattr(self.session.header, "seed_length", None) is not None:
                seed_len = self.session.header.seed_length or 0

            events = getattr(self.session, "events", [])[seed_len:]
            for event in events:
                if isinstance(event, dict) and event.get("type") == "agent/inbox/spliced":
                    data = event.get("data", {})
                    try:
                        self._apply(data)
                    except Exception as err:
                        seq = event.get("seq", "unknown")
                        raise ValueError(f"invalid persisted inbox splice at session seq {seq}") from err

    @property
    def next_turn(self) -> List[Dict[str, Any]]:
        return list(self._state["next-turn"])

    @property
    def next_step(self) -> List[Dict[str, Any]]:
        return list(self._state["next-step"])

    @property
    def has_pending(self) -> bool:
        return len(self._state["next-turn"]) > 0 or len(self._state["next-step"]) > 0

    def is_empty(self) -> bool:
        return not self.has_pending

    def _ensure_message_id(self, message: Dict[str, Any]) -> str:
        if "id" not in message:
            message["id"] = str(uuid.uuid4())
        return message["id"]

    def _locate(self, message_id: str) -> Optional[Tuple[str, int]]:
        for target in ("next-turn", "next-step"):
            for idx, msg in enumerate(self._state[target]):
                if msg.get("id") == message_id:
                    return target, idx
        return None

    def _validate(self, splice: Dict[str, Any]) -> None:
        target = splice.get("target", "next-turn")
        inbox = self._state[target]
        start = splice.get("start", 0)
        removed_count = splice.get("removedCount", 0)
        inserted = splice.get("inserted", [])

        if not isinstance(start, int) or start < 0 or start > len(inbox):
            raise ValueError("invalid inbox splice start position")
        if not isinstance(removed_count, int) or removed_count < 0 or start + removed_count > len(inbox):
            raise ValueError("invalid inbox splice removedCount")

        # Check for duplicate message ids
        candidate = inbox[:start] + inserted + inbox[start + removed_count :]
        other_queue = self._state["next-step"] if target == "next-turn" else self._state["next-turn"]
        all_candidate = candidate + other_queue

        ids = set()
        for msg in all_candidate:
            mid = msg.get("id")
            if mid:
                if mid in ids:
                    raise ValueError(f'message "{mid}" is already pending')
                ids.add(mid)

    def _apply(self, splice: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._validate(splice)
        target = splice.get("target", "next-turn")
        inbox = self._state[target]
        start = splice.get("start", 0)
        removed_count = splice.get("removedCount", 0)
        inserted = splice.get("inserted", [])

        removed = inbox[start : start + removed_count]
        self._state[target] = inbox[:start] + inserted + inbox[start + removed_count :]
        return removed

    def _mutate(
        self,
        target: str,
        start: int,
        delete_count: int,
        inserted: List[Dict[str, Any]],
        discard_removed: bool = True,
        turn: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        inbox = self._state[target]
        actual_start = max(0, min(start, len(inbox))) if start >= 0 else max(len(inbox) + start, 0)
        actual_delete_count = min(max(delete_count, 0), len(inbox) - actual_start)

        if actual_delete_count == 0 and len(inserted) == 0:
            return []

        for msg in inserted:
            self._ensure_message_id(msg)

        outcome = "canceled" if (discard_removed and actual_delete_count > 0) else None
        splice_data: Dict[str, Any] = {
            "target": target,
            "start": actual_start,
            "inserted": inserted,
        }
        if actual_delete_count > 0:
            splice_data["removedCount"] = actual_delete_count
        if outcome:
            splice_data["outcome"] = outcome

        self._validate(splice_data)

        # Durably log event to session if session is present
        if self.session and hasattr(self.session, "append"):
            try:
                self.session.append("agent/inbox/spliced", splice_data)
            except Exception:
                pass

        removed = inbox[actual_start : actual_start + actual_delete_count]
        self._state[target] = inbox[:actual_start] + inserted + inbox[actual_start + actual_delete_count :]

        if discard_removed and removed and self.ctx:
            for msg in removed:
                self.ctx.emit("agent/inbox/discarded", {"agent": self.agent, "message": msg})

        if inserted and self.ctx:
            for msg in inserted:
                self.ctx.emit("agent/inbox/inserted", {"agent": self.agent, "message": msg, "target": target})

        if turn is not None and removed and self.ctx:
            for msg in removed:
                self.ctx.emit("agent/inbox/claimed", {"agent": self.agent, "message": msg, "turn": turn})

        return removed

    def splice(
        self,
        target: str,
        start: int,
        delete_count: int,
        inserted: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return self._mutate(target, start, delete_count, inserted, discard_removed=True)

    def append(self, target: str, message: Dict[str, Any]) -> str:
        msg_id = self._ensure_message_id(message)
        t = "next-step" if target == "next-step" else "next-turn"
        self._mutate(t, len(self._state[t]), 0, [message], discard_removed=False)
        return msg_id

    def inject(self, message: Dict[str, Any]) -> str:
        """Inject message into next-step queue."""
        return self.append("next-step", message)

    def prepend(self, target: str, message: Dict[str, Any]) -> str:
        msg_id = self._ensure_message_id(message)
        t = "next-step" if target == "next-step" else "next-turn"
        self._mutate(t, 0, 0, [message], discard_removed=False)
        return msg_id

    def replace(self, message_id: str, new_message: Dict[str, Any]) -> bool:
        self._ensure_message_id(new_message)
        loc = self._locate(message_id)
        if not loc:
            return False
        target, index = loc
        self._mutate(target, index, 1, [new_message], discard_removed=True)
        return True

    def remove(self, message_id: str) -> bool:
        loc = self._locate(message_id)
        if not loc:
            return False
        target, index = loc
        self._mutate(target, index, 1, [], discard_removed=True)
        return True

    def claim(self, target: str = "next-turn", turn: int = 1) -> List[Dict[str, Any]]:
        claimed = self._mutate("next-step", 0, len(self._state["next-step"]), [], discard_removed=False, turn=turn)
        if target == "next-turn":
            claimed.extend(self._mutate("next-turn", 0, 1, [], discard_removed=False, turn=turn))
        return claimed

    def clear(self) -> None:
        self.splice("next-step", 0, len(self._state["next-step"]), [])
        self.splice("next-turn", 0, len(self._state["next-turn"]), [])
