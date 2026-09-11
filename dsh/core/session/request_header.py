"""
Request-header reconstruction utilities over full request/header session events.
Ported 1:1 from reference packages/core/session/src/request-header.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
from typing import Any, Dict, List, Optional, Sequence


def call_config_equals(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """
    Compare two LLM call configurations for equality.
    """
    if (
        a.get("provider") != b.get("provider")
        or a.get("model") != b.get("model")
        or a.get("reasoningEffort") != b.get("reasoningEffort")
        or a.get("temperature") != b.get("temperature")
        or a.get("maxTokens") != b.get("maxTokens")
    ):
        return False
    a_stop = a.get("stop")
    b_stop = b.get("stop")
    if a_stop is None or b_stop is None:
        return a_stop == b_stop
    return list(a_stop) == list(b_stop)


def canonical_header(header: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a header to canonical form: an empty system prompt and empty tool
    list become absent fields, matching how requests are built.
    """
    res: Dict[str, Any] = {"config": header.get("config", {})}
    adapter_defaults = header.get("adapterDefaults")
    if isinstance(adapter_defaults, dict):
        if adapter_defaults.get("reasoningEffort") is True or adapter_defaults.get("maxTokens") is True:
            res["adapterDefaults"] = dict(adapter_defaults)
    system = header.get("system")
    if system is not None and len(system) > 0:
        res["system"] = system
    tools = header.get("tools")
    if tools is not None and len(tools) > 0:
        res["tools"] = list(tools)
    return res


def _same_schema(a: Any, b: Any) -> bool:
    """
    Canonical JSON equality for tool schemas assembled through the same path.

    Mirrors reference `sameSchema` (`JSON.stringify(a) === JSON.stringify(b)`):
    key ORDER is part of the compared text, so two schemas carrying the same
    entries in a different insertion order are NOT equal (JSON.stringify keeps
    insertion order). `sort_keys` would have normalized that away.
    """
    return (
        json.dumps(a, separators=(",", ":"), ensure_ascii=False)
        == json.dumps(b, separators=(",", ":"), ensure_ascii=False)
    )


def header_equals(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """
    Field-wise equality over canonical headers. Tool schemas compare in order.
    Treats absent and empty tool arrays as equivalent canonical absence.
    """
    if not call_config_equals(a.get("config", {}), b.get("config", {})):
        return False
    a_def = a.get("adapterDefaults") or {}
    b_def = b.get("adapterDefaults") or {}
    if a_def.get("reasoningEffort") != b_def.get("reasoningEffort"):
        return False
    if a_def.get("maxTokens") != b_def.get("maxTokens"):
        return False
    if a.get("system") != b.get("system"):
        return False
    at = a.get("tools") or []
    bt = b.get("tools") or []
    if len(at) != len(bt):
        return False
    return all(_same_schema(x, y) for x, y in zip(at, bt))


def fold_request_header(
    events: Sequence[Dict[str, Any]],
    from_header: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fold the header events of a log into the EpochHeader in force after the last snapshot.
    """
    state = from_header
    for event in events:
        if event.get("type") == "request/header":
            hdr = event.get("data", {}).get("header")
            if isinstance(hdr, dict):
                state = canonical_header(hdr)
    return state


# CamelCase aliases
canonicalHeader = canonical_header
headerEquals = header_equals
foldRequestHeader = fold_request_header
