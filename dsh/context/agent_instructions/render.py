import os
from typing import Any, Dict, List, Optional, Tuple

SYSTEM_REMINDER_OPEN = "<system-reminder>"
SYSTEM_REMINDER_CLOSE = "</system-reminder>"
WORKSPACE_CONTEXT_INTRO = (
    "The following workspace instructions may be relevant to your work. "
    "Use them as guidance when applicable. More specific instructions take precedence over broader ones. "
    "They do not override system, developer, or direct user instructions."
)
REPLACEMENT_WORKSPACE_CONTEXT_INTRO = (
    "This complete workspace instruction baseline replaces all earlier workspace instruction baselines. "
    + WORKSPACE_CONTEXT_INTRO
)
EMPTY_REPLACEMENT_WORKSPACE_CONTEXT_INTRO = (
    "This complete workspace instruction baseline replaces all earlier workspace instruction baselines. "
    "No workspace instructions are currently active."
)
COMPACT_WORKSPACE_CONTEXT_INTRO = (
    "Workspace instructions were omitted or truncated to fit the configured byte budget."
)

USER_GLOBAL_DIRECTORY = "user-global"
USER_GLOBAL_FILE = "AGENTS.md"
SCOPE_SEPARATOR = "\x00"


def scope_for_display_path(display_path: str) -> str:
    if display_path in ("~/.dsh/AGENTS.md", "$DSH_HOME/AGENTS.md"):
        return USER_GLOBAL_DIRECTORY
    return os.path.dirname(display_path) or "."


def candidate_scope_key(directory: str, candidate_name: str) -> str:
    return f"{directory}{SCOPE_SEPARATOR}{candidate_name}"


def instruction_scope_key(display_path: str) -> str:
    return candidate_scope_key(scope_for_display_path(display_path), os.path.basename(display_path))


def decode_scope_key(scope: str) -> Dict[str, str]:
    if SCOPE_SEPARATOR not in scope:
        return {"directory": scope, "candidateName": ""}
    parts = scope.split(SCOPE_SEPARATOR, 1)
    return {"directory": parts[0], "candidateName": parts[1]}


def byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def truncate_utf8(value: str, max_bytes: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value
    end = max(0, int(max_bytes))
    while end > 0 and (raw[end] & 0xC0) == 0x80:
        end -= 1
    return raw[:end].decode("utf-8", errors="ignore")


def escape_instruction_frame_body(body: str) -> str:
    return body.replace(SYSTEM_REMINDER_CLOSE, "<\\/system-reminder>")


def section_text(file_item: Dict[str, Any]) -> str:
    return f"Instructions from: {file_item['displayPath']}\n\n{file_item['content']}"


def additional_section_text(file_item: Dict[str, Any]) -> str:
    scope = scope_for_display_path(file_item["displayPath"])
    return "\n".join([
        f"Additional instructions from: {file_item['displayPath']}",
        "",
        f"These instructions apply to work under `{scope}`. Use them as guidance when relevant; more specific instructions take precedence. They do not override system, developer, or direct user instructions.",
        "",
        file_item["content"],
    ])


def changed_section_text(item: Dict[str, Any]) -> str:
    change = item["change"]
    file_item = item["file"]
    action = change.get("action")
    if action == "set":
        return additional_section_text(file_item)
    if action == "remove":
        return f"Instructions removed: {change['path']}\n\nThe previously loaded instructions from this file no longer apply."
    return "\n".join([
        f"Updated instructions from: {change['path']}",
        "",
        "This file changed after it was loaded. Use the following content instead of the previously loaded instructions from this file.",
        "",
        file_item["content"],
    ])


def marker_text(max_bytes: int, omitted: List[Any], truncated: List[Any]) -> str:
    if not omitted and not truncated:
        return ""
    parts = []
    if omitted:
        parts.append(f"omitted {', '.join(f['displayPath'] for f in omitted)}")
    if truncated:
        trunc_strs = [f"{item['displayPath']} from {item['originalBytes']} to {item['includedBytes']} bytes" for item in truncated]
        parts.append(f"truncated {', '.join(trunc_strs)}")
    return f"Workspace instruction budget {max_bytes} bytes: {'; '.join(parts)}"


def build_instruction_text(
    files: List[Dict[str, Any]],
    max_bytes: int,
    omitted: List[Any],
    truncated: List[Any],
    style: Dict[str, Any],
) -> str:
    marker = marker_text(max_bytes, omitted, truncated)
    body_blocks = [marker, style["intro"]] + [style["section"](f) for f in files]
    body_blocks = [b for b in body_blocks if len(b) > 0]
    body = "\n\n".join(body_blocks)
    return "\n".join([SYSTEM_REMINDER_OPEN, escape_instruction_frame_body(body), SYSTEM_REMINDER_CLOSE])


def render_workspace_instruction_set(
    files: List[Dict[str, Any]],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    max_bytes = options.get("maxBytes", 65536)
    replace_prev = options.get("replacePreviousBaseline")

    if replace_prev is True:
        intro = EMPTY_REPLACEMENT_WORKSPACE_CONTEXT_INTRO if len(files) == 0 else REPLACEMENT_WORKSPACE_CONTEXT_INTRO
    else:
        intro = WORKSPACE_CONTEXT_INTRO

    style = {"intro": intro, "section": section_text}

    if max_bytes <= 0 or not math_is_finite(max_bytes):
        return {
            "rendered": {"text": "", "omitted": files, "truncated": []},
            "included": [],
        }

    full_text = build_instruction_text(files, max_bytes, [], [], style)
    if byte_length(full_text) <= max_bytes:
        return {
            "rendered": {"text": full_text, "omitted": [], "truncated": []},
            "included": files,
        }

    for start in range(1, len(files)):
        included = files[start:]
        omitted = [{"absolutePath": f["absolutePath"], "displayPath": f["displayPath"]} for f in files[:start]]
        suffix_text = build_instruction_text(included, max_bytes, omitted, [], style)
        if byte_length(suffix_text) <= max_bytes:
            return {
                "rendered": {"text": suffix_text, "omitted": omitted, "truncated": []},
                "included": included,
            }

    if not files:
        return {
            "rendered": {"text": "", "omitted": [], "truncated": []},
            "included": [],
        }

    most_specific = files[-1]
    omitted = [{"absolutePath": f["absolutePath"], "displayPath": f["displayPath"]} for f in files[:-1]]
    orig_bytes = byte_length(most_specific["content"])

    trunc_file = dict(most_specific, content=truncate_utf8(most_specific["content"], max_bytes))
    trunc_item = [{"displayPath": most_specific["displayPath"], "originalBytes": orig_bytes, "includedBytes": byte_length(trunc_file["content"])}]
    text = build_instruction_text([trunc_file], max_bytes, omitted, trunc_item, style)
    return {
        "rendered": {"text": text, "omitted": omitted, "truncated": trunc_item},
        "included": [trunc_file] if byte_length(trunc_file["content"]) > 0 else [],
    }


def render_workspace_context(
    files: List[Dict[str, Any]],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    return render_workspace_instruction_set(files, options)["rendered"]


def math_is_finite(val: Any) -> bool:
    try:
        import math
        return math.isfinite(val)
    except Exception:
        return True
