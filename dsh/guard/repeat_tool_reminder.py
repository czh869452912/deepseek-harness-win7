"""
Advisory per-agent repeat-call detector (`@deepseek-ai/dsh-repeat-tool-reminder`).
"""

import json
import re
from typing import Any, Dict, List, Optional, Set
from dsh.cordis.plugin import Plugin


def sort_json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [sort_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: sort_json_value(value[k]) for k in sorted(value.keys())}
    return value


def canonicalize(args: Any) -> str:
    sorted_val = sort_json_value(args)
    return json.dumps(sorted_val, sort_keys=True, ensure_ascii=False)


def wildcard_to_regex(pattern: str) -> re.Pattern:
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.compile(f"^{escaped}$")


def preview_arguments(canonical: str, cap: int) -> str:
    if len(canonical) <= cap:
        return canonical
    return f"{canonical[:cap]}… (+{len(canonical) - cap} more chars)"


def validate_thresholds(values: List[int]) -> List[int]:
    if not values:
        throw_err = ValueError("repeat-tool-reminder: `thresholds` must not be empty")
        raise throw_err
    for v in values:
        if not isinstance(v, int) or isinstance(v, bool) or v < 2:
            raise ValueError(f"repeat-tool-reminder: invalid threshold {v} — every threshold must be an integer >= 2")
    if len(set(values)) != len(values):
        raise ValueError("repeat-tool-reminder: `thresholds` must not contain duplicates")
    return sorted(values)


GENTLE_REMINDER = (
    "You are repeating the exact same tool call with identical arguments. "
    "Carefully analyze the previous result before calling again: if the task is "
    "not complete, try a different approach or different arguments instead of "
    "repeating the call."
)


def detailed_reminder(tool_name: str, count: int, canonical_args: str) -> str:
    return (
        "Repeated tool call detected:\n"
        f"- tool: {tool_name}\n"
        f"- consecutive_calls: {count}\n"
        f"- arguments: {canonical_args}\n"
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
        cfg = config or {}
        raw_thresholds = cfg.get("thresholds", [3, 5, 8])
        self.thresholds = validate_thresholds(raw_thresholds)
        self.threshold_set = set(self.thresholds)
        
        self.include_patterns = [wildcard_to_regex(p) for p in cfg.get("include", [])]
        self.exclude_patterns = [wildcard_to_regex(p) for p in cfg.get("exclude", [])]
        
        preview_chars = cfg.get("argumentsPreviewChars", cfg.get("arguments_preview_chars", 500))
        if not isinstance(preview_chars, int) or isinstance(preview_chars, bool) or preview_chars < 1:
            raise ValueError(f"repeat-tool-reminder: invalid argumentsPreviewChars {preview_chars} — must be an integer >= 1")
        self.arguments_preview_chars = preview_chars

        self._history: Dict[str, Dict[str, Any]] = {}

    def tracked(self, tool_name: str) -> bool:
        if self.include_patterns and not any(p.match(tool_name) for p in self.include_patterns):
            return False
        return not any(p.match(tool_name) for p in self.exclude_patterns)

    def record_and_check(self, session_id: str, tool_name: str, args: Any) -> Optional[str]:
        if not self.tracked(tool_name):
            return None
        canonical = canonicalize(args)
        key = json.dumps([tool_name, canonical])
        state = self._history.get(session_id, {"last_key": "", "count": 0})

        if state["last_key"] == key:
            state["count"] += 1
        else:
            state["last_key"] = key
            state["count"] = 1

        self._history[session_id] = state
        count = state["count"]

        if count in self.threshold_set:
            if count == self.thresholds[0]:
                return GENTLE_REMINDER
            else:
                prev_args = preview_arguments(canonical, self.arguments_preview_chars)
                return detailed_reminder(tool_name, count, prev_args)
        return None

    def apply(self, ctx: Any) -> None:
        ctx.set_service("repeat_tool_reminder", self)

        def on_post_execute(exec_data: Any, result_data: Any = None) -> None:
            tool_name = exec_data.get("name", "") if isinstance(exec_data, dict) else getattr(exec_data, "name", "")
            args = exec_data.get("arguments", {}) if isinstance(exec_data, dict) else getattr(exec_data, "arguments", {})
            session_id = exec_data.get("session_id", "default") if isinstance(exec_data, dict) else "default"

            reminder = self.record_and_check(session_id, tool_name, args)
            if reminder and ctx.has("agents"):
                agents_svc = ctx.get("agents")
                agent = agents_svc.get(session_id) if hasattr(agents_svc, "get") else None
                if agent and hasattr(agent, "inbox") and hasattr(agent.inbox, "push"):
                    agent.inbox.push({
                        "role": "user",
                        "content": reminder,
                        "source": {"kind": "plugin", "plugin": "repeat-tool-reminder"},
                    })

        ctx.on("tools/post-execute", on_post_execute)

        def on_pre_step(payload: Dict[str, Any]) -> None:
            messages = payload.get("messages", [])
            session_id = payload.get("session_id", "default")
            if any(isinstance(m, dict) and m.get("role") == "user" for m in messages):
                if session_id in self._history:
                    del self._history[session_id]

        ctx.on("agent/pre-step", on_pre_step)
