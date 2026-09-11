"""
Types, constants, and utility functions for SystemPrompt.
Strict 1:1 parity with reference/packages/core/system-prompt/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import functools
import json
import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Union


class _FirstPartySectionOrder(dict):
    """Dict subclass allowing attribute access for section orders."""
    def __getattr__(self, name: str) -> int:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


FIRST_PARTY_SECTION_ORDER = _FirstPartySectionOrder({
    "HARNESS_IDENTITY": -1000,
    "HARNESS_SOURCE": -900,
    "WEB_SURFACE": -800,
    "DEPLOYMENT_PERSONA": 0,
    "PLAN_POLICY": 500,
    "TEAM_POLICY": 600,
    "PTC_ONLY": 800,
    "FILE_REFERENCE": 900,
    "TOOL_BASH": 1000,
    "TOOL_PWSH": 1010,
    "TOOL_READ": 1100,
    "TOOL_WRITE": 1200,
    "TOOL_EDIT": 1300,
    "TOOL_GLOB": 1400,
    "TOOL_GREP": 1500,
    "TOOL_JOBS": 1600,
    "TOOL_PTY": 1700,
    "TOOL_WEB_SEARCH": 2000,
    "TOOL_WEB_FETCH": 2100,
    "TOOL_LSP": 2200,
    "TOOL_SESSION_QUERY": 2300,
    "TOOL_GOAL": 2400,
    "TOOL_CORDIS": 2500,
    "TOOL_WORKFLOW": 2600,
    "TOOL_RALPH": 2700,
    "TOOL_SUBAGENT": 2800,
    "TOOL_REPORT": 2900,
    "TOOLS_SDK": 5000,
    "DELIVERABLE_FILE_REFERENCES": 9000,
    "STRUCTURED_OUTPUT": 9900,
})

PERSONA_SECTION = "deployment:persona"
PERSONA_ORDER = FIRST_PARTY_SECTION_ORDER["DEPLOYMENT_PERSONA"]

TOOL_ORDER_REST = "<unlisted-tools>"

VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
GROUP_AT = re.compile(r"^\{\{([^{}]*)\}\}")


class PromptSection:
    """One contributed section of the system prompt."""

    def __init__(
        self,
        name: str,
        order: float,
        text: Union[str, Callable[[Dict[str, Any]], str]],
        complete: bool = False,
    ):
        self.name = name
        self.order = order
        self.text = text
        self.complete = complete

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "order": self.order,
            "text": self.text,
            "complete": self.complete,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class PromptContext:
    """Dynamic model context materialized as a durable snapshot."""

    def __init__(
        self,
        name: str,
        order: float,
        text: Union[str, Callable[[Dict[str, Any]], str]],
    ):
        self.name = name
        self.order = order
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "order": self.order,
            "text": self.text,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AssembledSection:
    """One section of an assembly: PromptSection with its text resolved."""

    def __init__(self, name: str, text: str):
        self.name = name
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "text": self.text}

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AssembledContext:
    """One resolved dynamic context contribution."""

    def __init__(self, name: str, text: str):
        self.name = name
        self.text = text

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "text": self.text}

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AssembledItem(dict):
    """Dictionary subclass representing an assembled section, context, or tool with attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


class AssembledItemList(list):
    """List subclass that transparently wraps dict items into AssembledItem on insertion."""

    def __init__(self, iterable: Optional[Any] = None):
        super().__init__()
        if iterable:
            for item in iterable:
                self.append(item)

    def append(self, item: Any) -> None:
        if isinstance(item, dict) and not isinstance(item, AssembledItem):
            item = AssembledItem(item)
        super().append(item)

    def insert(self, index: int, item: Any) -> None:
        if isinstance(item, dict) and not isinstance(item, AssembledItem):
            item = AssembledItem(item)
        super().insert(index, item)

    def extend(self, iterable: Any) -> None:
        for item in iterable:
            self.append(item)

    def __setitem__(self, index: Any, item: Any) -> None:
        if isinstance(item, dict) and not isinstance(item, AssembledItem):
            item = AssembledItem(item)
        super().__setitem__(index, item)


class PromptAssembly(dict):
    """
    Dictionary subclass representing an assembled system prompt.
    Supports both dict indexing and attribute access.
    """

    def __init__(
        self,
        *args: Any,
        sections: Optional[List[Any]] = None,
        contexts: Optional[List[Any]] = None,
        tools: Optional[List[Any]] = None,
        variables: Optional[Dict[str, Optional[str]]] = None,
        **kwargs: Any,
    ):
        super().__init__()
        if args and isinstance(args[0], dict):
            src = args[0]
            self["sections"] = AssembledItemList(src.get("sections", []))
            self["contexts"] = AssembledItemList(src.get("contexts", []))
            self["tools"] = AssembledItemList(src.get("tools", []))
            self["variables"] = dict(src.get("variables", {}))
            for k, v in src.items():
                if k not in ("sections", "contexts", "tools", "variables"):
                    self[k] = v
        else:
            self["sections"] = AssembledItemList(sections or [])
            self["contexts"] = AssembledItemList(contexts or [])
            self["tools"] = AssembledItemList(tools or [])
            self["variables"] = dict(variables or {})
            for k, v in kwargs.items():
                self[k] = v

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


AssembleContext = Dict[str, Any]


class ToolProviderResult:
    """Tool schemas visible in one assembly and their pre-restriction name set."""

    def __init__(
        self,
        schemas: List[Dict[str, Any]],
        known_names: Optional[Sequence[str]] = None,
    ):
        self.schemas = list(schemas)
        self.known_names = list(known_names) if known_names is not None else None
        self.knownNames = self.known_names


def compare_names(a: str, b: str) -> int:
    """Code-unit name comparison (locale-independent)."""
    return -1 if a < b else (1 if a > b else 0)


def compare_prompt_sections(a: Any, b: Any) -> int:
    """Order prompt sections by their explicit placement, then deterministically by name."""
    a_order = getattr(a, "order", None) if not isinstance(a, dict) else a.get("order", 0)
    b_order = getattr(b, "order", None) if not isinstance(b, dict) else b.get("order", 0)
    a_name = getattr(a, "name", "") if not isinstance(a, dict) else a.get("name", "")
    b_name = getattr(b, "name", "") if not isinstance(b, dict) else b.get("name", "")
    diff = a_order - b_order
    if diff != 0:
        return -1 if diff < 0 else 1
    return compare_names(a_name, b_name)


def compare_tool_names(a: Any, b: Any) -> int:
    """Order tool schemas lexicographically by name."""
    a_name = getattr(a, "name", "") if not isinstance(a, dict) else a.get("name", "")
    b_name = getattr(b, "name", "") if not isinstance(b, dict) else b.get("name", "")
    return compare_names(a_name, b_name)


def validate_tool_order(tool_order: Optional[List[str]]) -> Optional[List[str]]:
    """
    Validate duplicate names and the required TOOL_ORDER_REST marker.
    """
    if tool_order is None:
        return None
    seen = set()
    for name in tool_order:
        if name in seen:
            raise ValueError(f'toolOrder lists "{name}" more than once')
        seen.add(name)
    if TOOL_ORDER_REST not in seen:
        raise ValueError(f'toolOrder must contain the "{TOOL_ORDER_REST}" rest entry (where unlisted tools are inserted)')
    return list(tool_order)


def order_tools(
    tools: List[Any],
    tool_order: Optional[List[str]],
    known_names: Set[str],
) -> List[Dict[str, Any]]:
    """
    Apply configured tool order, inserting unlisted tools lexicographically at TOOL_ORDER_REST.
    """
    tool_dicts: List[Dict[str, Any]] = []
    for t in tools:
        if isinstance(t, dict):
            tool_dicts.append(t)
        else:
            tool_dicts.append({
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", ""),
                "parameters": getattr(t, "parameters", {}),
            })

    for t in tool_dicts:
        if t.get("name") == TOOL_ORDER_REST:
            raise ValueError(f'tool provider returned reserved tool name "{TOOL_ORDER_REST}" (reserved for toolOrder\'s rest entry)')

    if tool_order is None:
        return sorted(tool_dicts, key=functools.cmp_to_key(compare_tool_names))

    unknown = [name for name in tool_order if name != TOOL_ORDER_REST and name not in known_names]
    if unknown:
        formatted_unknown = ", ".join(f'"{name}"' for name in unknown)
        known_str = ", ".join(sorted(known_names)) or "(none)"
        raise ValueError(f'toolOrder lists unregistered tool{"s" if len(unknown) > 1 else ""} {formatted_unknown}; known tools: {known_str}')

    listed = set(tool_order)
    rest = sorted([t for t in tool_dicts if t.get("name") not in listed], key=functools.cmp_to_key(compare_tool_names))

    ordered_res: List[Dict[str, Any]] = []
    for name in tool_order:
        if name == TOOL_ORDER_REST:
            ordered_res.extend(rest)
        else:
            ordered_res.extend([t for t in tool_dicts if t.get("name") == name])
    return ordered_res


def interpolate_text(
    input_item: Any,
    variables: Dict[str, Optional[str]],
    kind: str = "section",
) -> str:
    """
    Interpolate strict {{variable}} references, handling diagnostics.
    """
    item_name = input_item.get("name", "") if isinstance(input_item, dict) else getattr(input_item, "name", "")
    text = input_item.get("text", "") if isinstance(input_item, dict) else getattr(input_item, "text", "")
    if not isinstance(text, str):
        text = str(text) if text is not None else ""

    result = ""
    last = 0

    while True:
        open_pos = text.find("{{", last)
        if open_pos < 0:
            break
        match = GROUP_AT.match(text[open_pos:])
        if match is None:
            if text.find("}}", open_pos + 2) >= 0:
                snippet = text[open_pos : open_pos + 16]
                raise ValueError(f'malformed prompt variable reference at "{snippet}…" in {kind} "{item_name}" (references are complete simple {{name}} groups)')
            result += text[last : open_pos + 2]
            last = open_pos + 2
            continue

        raw_group = match.group(0)
        var_name = match.group(1)
        if not VARIABLE_NAME.match(var_name):
            raise ValueError(f'malformed prompt variable reference "{{{{{var_name}}}}}" in {kind} "{item_name}" (variable names match /^[a-z][a-z0-9_]*$/)')

        if var_name not in variables:
            known = list(variables.keys())
            known_str = ", ".join(known) if len(known) > 0 else "(none)"
            raise ValueError(f'unknown prompt variable "{{{{{var_name}}}}}" in {kind} "{item_name}"; registered variables: {known_str}')

        val = variables[var_name]
        if val is None:
            raise ValueError(f'prompt variable "{{{{{var_name}}}}}" has no value for this assembly ({kind} "{item_name}")')

        result += text[last:open_pos] + str(val)
        last = open_pos + len(raw_group)

    return result + text[last:]


interpolate = interpolate_text


def render_prompt(assembly: Dict[str, Any]) -> str:
    """
    Interpolate strict {{variable}} references, drop empty sections, and join with blank lines.
    """
    sections = assembly.get("sections", [])
    variables = assembly.get("variables", {})
    rendered = [interpolate_text(s, variables, "section") for s in sections]
    non_empty = [t for t in rendered if len(t) > 0]
    return "\n\n".join(non_empty)


def render_context_sections(assembly: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Render context contributions into non-empty attributed snapshot sections.
    """
    contexts = assembly.get("contexts", [])
    variables = assembly.get("variables", {})
    res: List[Dict[str, Any]] = []
    for ctx in contexts:
        name = ctx.get("name", "") if isinstance(ctx, dict) else getattr(ctx, "name", "")
        text = interpolate_text(ctx, variables, "context")
        if len(text) > 0:
            res.append({"name": name, "text": text})
    return res


def join_context_sections(sections: Sequence[Any]) -> str:
    """
    Join rendered context sections into complete model-facing runtime context snapshot.
    """
    texts = [s.get("text", "") if isinstance(s, dict) else getattr(s, "text", "") for s in sections]
    body = "\n\n".join(texts)
    if not body:
        return ""
    return f"Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n{body}"


def render_context_snapshot(assembly: Dict[str, Any]) -> str:
    """
    Render complete dynamic runtime context snapshot.
    """
    return join_context_sections(render_context_sections(assembly))


renderPrompt = render_prompt
renderContextSnapshot = render_context_snapshot
renderContextSections = render_context_sections
joinContextSections = join_context_sections
interpolateText = interpolate_text
