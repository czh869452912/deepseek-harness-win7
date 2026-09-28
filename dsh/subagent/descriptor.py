"""Versioned durable child identity and declared cold-resume composition."""
import copy

from dsh.core.session.json import snapshot_json_value

VERSION = 3
BASE_KEYS = {"version", "mode", "provider", "label"}
COMPOSITION_KEYS = {"agentProvider", "agentModel", "agentReasoningEffort", "persona", "toolFilter"}


def parse_descriptor(value):
    if not isinstance(value, dict):
        raise ValueError("persisted subagent descriptor payload must be an object")
    if type(value.get("version")) not in (int, float):
        raise ValueError("persisted subagent descriptor version must be a number")
    if value["version"] != VERSION:
        return None
    mode = value.get("mode")
    if mode not in ("one-shot", "continuable"):
        raise ValueError("persisted subagent descriptor mode must be one-shot or continuable")
    allowed = BASE_KEYS | (COMPOSITION_KEYS if mode == "continuable" else set())
    if set(value) - allowed:
        raise ValueError("persisted subagent descriptor has unknown fields")
    if not isinstance(value.get("provider"), str):
        raise ValueError("persisted subagent descriptor provider must be a string")
    if mode == "continuable" and not isinstance(value.get("label"), str):
        raise ValueError("persisted subagent descriptor label must be a string")
    for key in (BASE_KEYS | COMPOSITION_KEYS) - {"version", "toolFilter"}:
        if key in value and not isinstance(value[key], str):
            raise ValueError("persisted subagent descriptor {} must be a string".format(key))
    if "toolFilter" in value:
        restriction = value["toolFilter"]
        if not isinstance(restriction, dict) or not restriction or set(restriction) - {"allow", "deny"}:
            raise ValueError("persisted toolFilter must declare allow and/or deny")
        for items in restriction.values():
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError("persisted toolFilter values must be arrays of strings")
    return copy.deepcopy(value)


def snapshot_descriptor(value):
    keys = {"mode", "provider", "label"} | (COMPOSITION_KEYS if value["mode"] == "continuable" else set())
    candidate = {key: value[key] for key in keys if key in value}
    candidate["version"] = VERSION
    missing = object()
    snapshot = snapshot_json_value(candidate, missing)
    if snapshot is missing:
        raise ValueError("subagent descriptor is not losslessly JSON-serializable")
    return snapshot


def fold_descriptor(events):
    for event in events:
        if event["type"] == "subagent/descriptor":
            return parse_descriptor(event["data"])
    return None


def completed_turn_prefix(parent):
    events = parent.session.events
    for event in reversed(events):
        if event["type"] == "turn/end":
            return list(events[:event["seq"] + 1])
    return []


def final_assistant_output(events):
    message, partial = None, []
    for event in events:
        if event["type"] == "assistant/message":
            content = event["data"]["message"]["content"]
            if content:
                message = content
        elif event["type"] == "assistant/chunk":
            chunk = event["data"]["chunk"]
            if chunk.get("type") == "text-delta" and chunk["text"]:
                partial.append(chunk["text"])
    return copy.deepcopy(message) if message is not None else [{"type": "text", "text": "".join(partial)}] if partial else None
