import json
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


def sort_json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [sort_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: sort_json_value(value[k]) for k in sorted(value.keys())}
    return value


def canonicalize_args(args: Any) -> str:
    sorted_val = sort_json_value(args)
    return json.dumps(sorted_val, sort_keys=True, ensure_ascii=False)


GENTLE_REMINDER = (
    "You are repeating the exact same tool call with identical arguments. "
    "Carefully analyze the previous result before calling again: if the task is "
    "not complete, try a different approach or different arguments instead of "
    "repeating the call."
)


def detailed_reminder(tool_name: str, count: int, canonical_args: str, max_chars: int = 500) -> str:
    preview = canonical_args[:max_chars] if len(canonical_args) > max_chars else canonical_args
    return (
        "Repeated tool call detected:\n"
        f"- tool: {tool_name}\n"
        f"- consecutive_calls: {count}\n"
        f"- arguments: {preview}\n"
        "The repeated calls are not making progress. Do not call this tool with "
        "these exact arguments again. Inspect the latest result and choose a "
        "different action, different arguments, or finish the task if enough "
        "evidence has been gathered."
    )


class RepeatToolReminderPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-repeat-tool-reminder`: Advisory repeat tool call guard.
    """

    id = "repeat-tool-reminder"
    name = "@deepseek-ai/dsh-repeat-tool-reminder"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.thresholds: List[int] = self.config.get("thresholds", [3, 5, 8])
        self.arguments_preview_chars: int = int(self.config.get("argumentsPreviewChars", 500))
        self._history: Dict[str, Dict[str, Any]] = {}

    def record_and_check(self, session_id: str, tool_name: str, args: Any) -> Optional[str]:
        key = f"{tool_name}:{canonicalize_args(args)}"
        state = self._history.get(session_id, {"last_call": "", "count": 0})

        if state["last_call"] == key:
            state["count"] += 1
        else:
            state["last_call"] = key
            state["count"] = 1

        self._history[session_id] = state

        count = state["count"]
        if count in self.thresholds:
            if count == self.thresholds[0]:
                return GENTLE_REMINDER
            else:
                return detailed_reminder(
                    tool_name=tool_name,
                    count=count,
                    canonical_args=key[len(tool_name) + 1:],
                    max_chars=self.arguments_preview_chars,
                )
        return None

    def apply(self, ctx: Any) -> None:
        ctx.set_service("repeat_tool_reminder", self)
