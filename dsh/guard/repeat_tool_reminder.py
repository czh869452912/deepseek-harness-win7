"""
Advisory per-agent repeat-call detector (`@deepseek-ai/dsh-repeat-tool-reminder`).
"""

import json
import math
import re
import weakref
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _js_number_to_string, _js_own_enumerable_keys, _js_string_length
from dsh.llm.message import create_user_message


def _normalize_string(value: str) -> str:
    return value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def sort_json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [sort_json_value(v) for v in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("repeat-tool-reminder: arguments must have JSON string keys")
        normalized = {_normalize_string(key): item for key, item in value.items()}
        # Preserve __proto__ as data; upstream's ordinary-object assignment drops it.
        ordered = {key: sort_json_value(normalized[key]) for key in sorted(
            normalized, key=lambda item: item.encode("utf-16-be", "surrogatepass"))}
        return {key: ordered[key] for key in _js_own_enumerable_keys(ordered)}
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = _js_number_to_string(value)
        return "null" if number in ("NaN", "Infinity", "-Infinity") else number
    if isinstance(value, str):
        rendered = json.dumps(_normalize_string(value), ensure_ascii=False)
        return rendered.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, list):
        return "[" + ",".join(_stringify(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(_stringify(key) + ":" + _stringify(item)
                              for key, item in value.items()) + "}"
    raise TypeError("repeat-tool-reminder: arguments must be parsed JSON or a raw string")


def canonicalize(args: Any) -> str:
    return _stringify(sort_json_value(args))


def wildcard_to_regex(pattern: str) -> re.Pattern:
    escaped = re.escape(_normalize_string(pattern)).replace(r"\*", "[^\n\r\u2028\u2029]*")
    return re.compile(r"\A" + escaped + r"\Z")


def preview_arguments(canonical: str, cap: int) -> str:
    length = _js_string_length(canonical)
    if length <= cap:
        return canonical
    head = canonical.encode("utf-16-le", "surrogatepass")[:cap * 2].decode("utf-16-le", "surrogatepass")
    return f"{head}… (+{length - cap} more chars)"


def _integer(value: Any) -> bool:
    try:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and int(value) == value)
    except OverflowError:
        return False


def validate_thresholds(values: List[int]) -> List[int]:
    if not isinstance(values, list):
        raise ValueError("repeat-tool-reminder: `thresholds` must be an array")
    if not values:
        raise ValueError("repeat-tool-reminder: `thresholds` must not be empty")
    for v in values:
        if not _integer(v) or v < 2:
            raise ValueError(f"repeat-tool-reminder: invalid threshold {v} — every threshold must be an integer >= 2")
    if len(set(values)) != len(values):
        raise ValueError("repeat-tool-reminder: `thresholds` must not contain duplicates")
    return sorted(int(value) for value in values)


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
    Config = Schema.object(dict(
        thresholds=Schema.array(Schema.number()).default([3, 5, 8]),
        include=Schema.array(Schema.string()).default([]),
        exclude=Schema.array(Schema.string()).default([]),
        argumentsPreviewChars=Schema.number().default(500),
    ))

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        raw_thresholds = cfg.get("thresholds", [3, 5, 8])
        self.thresholds = validate_thresholds(raw_thresholds)
        self.threshold_set = set(self.thresholds)
        
        for field in ("include", "exclude"):
            patterns = cfg.get(field, [])
            if not isinstance(patterns, list) or any(not isinstance(item, str) for item in patterns):
                raise ValueError("repeat-tool-reminder: `{}` must be an array of strings".format(field))
        self.include_patterns = [wildcard_to_regex(p) for p in cfg.get("include", [])]
        self.exclude_patterns = [wildcard_to_regex(p) for p in cfg.get("exclude", [])]
        
        preview_chars = cfg.get("argumentsPreviewChars", cfg.get("arguments_preview_chars", 500))
        if not _integer(preview_chars) or preview_chars < 1:
            raise ValueError(f"repeat-tool-reminder: invalid argumentsPreviewChars {preview_chars} — must be an integer >= 1")
        self.arguments_preview_chars = int(preview_chars)

        self._history: Dict[str, Dict[str, Any]] = {}

    def tracked(self, tool_name: str) -> bool:
        tool_name = _normalize_string(tool_name)
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
        chains = weakref.WeakKeyDictionary()

        async def on_post_execute(exec_data: Any, result_data: Any, next_fn: Any) -> Any:
            tool_name = exec_data.get("name", "") if isinstance(exec_data, dict) else getattr(exec_data, "name", "")
            args = exec_data.get("arguments", {}) if isinstance(exec_data, dict) else getattr(exec_data, "arguments", {})
            agent = exec_data.get("agent") if isinstance(exec_data, dict) else getattr(exec_data, "agent", None)
            reminder = None
            if agent is not None and self.tracked(tool_name):
                canonical = canonicalize(args)
                key = (tool_name, canonical)
                old_key, old_count = chains.get(agent, (None, 0))
                count = old_count + 1 if key == old_key else 1
                chains[agent] = (key, count)
                if count in self.threshold_set:
                    reminder = GENTLE_REMINDER if count == self.thresholds[0] else detailed_reminder(
                        tool_name, count, preview_arguments(canonical, self.arguments_preview_chars))
            notice = None
            if reminder is not None:
                notice = create_user_message(dict(content=[dict(type="text", text=reminder)],
                    source=dict(kind="plugin", plugin="repeat-tool-reminder", form="notice",
                                summary="{} × {}".format(tool_name, count))))
            decision = await next_fn()
            if notice is not None:
                contexts = [notice] + list(decision.get("additionalContexts") or [])
                if decision.get("kind") == "block":
                    return dict(kind="block", feedback=decision.get("feedback"), additionalContexts=contexts)
                decision = dict(decision, additionalContexts=contexts)
            return decision

        ctx.on("tools/post-execute", on_post_execute)

        async def on_pre_step(payload: Dict[str, Any], next_fn: Any) -> Any:
            messages = payload.get("messages", [])
            agent = payload.get("agent")
            if agent is not None and any(isinstance(m, dict) and (m.get("source") or {}).get("kind") == "user" for m in messages):
                chains.pop(agent, None)
            return await next_fn()

        ctx.on("agent/pre-step", on_pre_step)
