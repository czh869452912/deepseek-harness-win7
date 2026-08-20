from typing import Any, Dict, List, Optional


class SessionService:
    """
    Session event log service registered at `ctx.sessions`.
    Maintains append-only session events and projects model history.
    """

    def __init__(self, session_id: str = "default-session"):
        self.session_id = session_id
        self.events: List[Dict[str, Any]] = []

    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "type": event_type,
            "session_id": self.session_id,
            "data": data
        }
        self.events.append(event)
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

    def derive_messages(self, system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Derive messages list for LLM API call from session event history.
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
