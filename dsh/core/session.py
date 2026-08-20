from typing import Any, Dict, List, Optional


class SessionService:
    """
    Event-Sourced Session Service mounted at `ctx.sessions`.
    Maintains append-only session log and projects LLM message history.
    Emits `session/event` and `session/flush` Cordis lifecycle events.
    """

    def __init__(self, session_id: str = "default-session", ctx: Optional[Any] = None):
        self.session_id = session_id
        self.ctx = ctx
        self.events: List[Dict[str, Any]] = []

    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        seq = len(self.events) + 1
        event = {
            "seq": seq,
            "type": event_type,
            "session_id": self.session_id,
            "data": data
        }
        self.events.append(event)

        if self.ctx:
            self.ctx.emit("session/event", self, event)

        return event

    def append_user_message(self, text: str) -> None:
        self.append_event("user/message", {"content": text})

    def append_assistant_message(self, message: Dict[str, Any]) -> None:
        self.append_event("assistant/message", {"message": message})

    def append_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        self.append_event("tool/result", {
            "tool_call_id": tool_call_id,
            "name": name,
            "result": result
        })

    async def flush(self) -> None:
        if self.ctx:
            await self.ctx.parallel("session/flush", self)

    def derive_messages(self, system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Derive messages array for LLM API call from append-only session log.
        """
        messages: List[Dict[str, Any]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for event in self.events:
            etype = event["type"]
            edata = event["data"]

            if etype == "user/message":
                messages.append({"role": "user", "content": edata["content"]})
            elif etype == "assistant/message":
                messages.append(edata["message"])
            elif etype == "tool/result":
                messages.append({
                    "role": "tool",
                    "tool_call_id": edata["tool_call_id"],
                    "name": edata.get("name", ""),
                    "content": str(edata["result"])
                })

        return messages
