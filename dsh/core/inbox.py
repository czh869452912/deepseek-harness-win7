"""
Durable Agent Inbox projection maintaining next_turn and next_step queues.
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple


class Inbox:
    """
    Agent-owned projection of durable pending work.
    Manages next_turn (future turns) and next_step (mid-turn steering / injected context).
    """

    def __init__(self, ctx: Optional[Any] = None, agent: Optional[Any] = None):
        self.ctx = ctx
        self.agent = agent
        self.next_turn: List[Dict[str, Any]] = []
        self.next_step: List[Dict[str, Any]] = []

    def _ensure_message_id(self, message: Dict[str, Any]) -> str:
        if "id" not in message:
            message["id"] = str(uuid.uuid4())
        return message["id"]

    def append(self, target: str, message: Dict[str, Any]) -> str:
        msg_id = self._ensure_message_id(message)
        if target == "next-step":
            self.next_step.append(message)
        else:
            self.next_turn.append(message)

        if self.ctx:
            self.ctx.emit("agent/inbox/inserted", {"agent": self.agent, "message": message, "target": target})
        return msg_id

    def prepend(self, target: str, message: Dict[str, Any]) -> str:
        msg_id = self._ensure_message_id(message)
        if target == "next-step":
            self.next_step.insert(0, message)
        else:
            self.next_turn.insert(0, message)

        if self.ctx:
            self.ctx.emit("agent/inbox/inserted", {"agent": self.agent, "message": message, "target": target})
        return msg_id

    def replace(self, message_id: str, new_message: Dict[str, Any]) -> bool:
        self._ensure_message_id(new_message)
        for i, m in enumerate(self.next_turn):
            if m.get("id") == message_id:
                old = self.next_turn[i]
                self.next_turn[i] = new_message
                if self.ctx:
                    self.ctx.emit("agent/inbox/discarded", {"agent": self.agent, "message": old})
                    self.ctx.emit("agent/inbox/inserted", {"agent": self.agent, "message": new_message, "target": "next-turn"})
                return True

        for i, m in enumerate(self.next_step):
            if m.get("id") == message_id:
                old = self.next_step[i]
                self.next_step[i] = new_message
                if self.ctx:
                    self.ctx.emit("agent/inbox/discarded", {"agent": self.agent, "message": old})
                    self.ctx.emit("agent/inbox/inserted", {"agent": self.agent, "message": new_message, "target": "next-step"})
                return True

        return False

    def remove(self, message_id: str) -> Optional[Dict[str, Any]]:
        for i, m in enumerate(self.next_turn):
            if m.get("id") == message_id:
                old = self.next_turn.pop(i)
                if self.ctx:
                    self.ctx.emit("agent/inbox/discarded", {"agent": self.agent, "message": old})
                return old

        for i, m in enumerate(self.next_step):
            if m.get("id") == message_id:
                old = self.next_step.pop(i)
                if self.ctx:
                    self.ctx.emit("agent/inbox/discarded", {"agent": self.agent, "message": old})
                return old

        return None

    def claim(self, target: str = "next-turn") -> List[Dict[str, Any]]:
        """
        Claim pending messages:
        - 'next-step': claims all pending next_step items.
        - 'next-turn': claims all pending next_step items plus the head of next_turn.
        """
        claimed: List[Dict[str, Any]] = []

        if self.next_step:
            claimed.extend(self.next_step)
            self.next_step.clear()

        if target == "next-turn" and self.next_turn:
            claimed.append(self.next_turn.pop(0))

        if self.ctx and claimed:
            for msg in claimed:
                self.ctx.emit("agent/inbox/claimed", {"agent": self.agent, "message": msg})

        return claimed

    def clear(self) -> None:
        all_msgs = list(self.next_turn) + list(self.next_step)
        self.next_turn.clear()
        self.next_step.clear()
        if self.ctx:
            for msg in all_msgs:
                self.ctx.emit("agent/inbox/discarded", {"agent": self.agent, "message": msg})

    def is_empty(self) -> bool:
        return len(self.next_turn) == 0 and len(self.next_step) == 0
