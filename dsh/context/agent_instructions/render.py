import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

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


def with_truncated_content(file_item: Dict[str, Any], included_bytes: int) -> Dict[str, Any]:
    return dict(file_item, content=truncate_utf8(file_item["content"], included_bytes))


def truncate_to_fit(
    file_item: Dict[str, Any],
    included_files: List[Dict[str, Any]],
    max_bytes: int,
    omitted: List[Dict[str, Any]],
    style: Dict[str, Any],
) -> Dict[str, Any]:
    original_bytes = byte_length(file_item["content"])
    low = 0
    high = original_bytes
    best = with_truncated_content(file_item, 0)
    while low <= high:
        mid = (low + high) // 2
        candidate = with_truncated_content(file_item, mid)
        truncated = [{
            "displayPath": file_item["displayPath"],
            "originalBytes": original_bytes,
            "includedBytes": byte_length(candidate["content"]),
        }]
        text = build_instruction_text(included_files + [candidate], max_bytes, omitted, truncated, style)
        if byte_length(text) <= max_bytes:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def render_instruction_context(
    files: List[Dict[str, Any]],
    max_bytes: int,
    style: Dict[str, Any],
) -> Dict[str, Any]:
    if max_bytes <= 0 or not math_is_finite(max_bytes):
        return {"text": "", "omitted": files, "truncated": [], "represented": []}

    full_text = build_instruction_text(files, max_bytes, [], [], style)
    if byte_length(full_text) <= max_bytes:
        return {"text": full_text, "omitted": [], "truncated": [], "represented": files}

    for start in range(1, len(files)):
        included = files[start:]
        omitted = [{"absolutePath": f["absolutePath"], "displayPath": f["displayPath"]} for f in files[:start]]
        suffix_text = build_instruction_text(included, max_bytes, omitted, [], style)
        if byte_length(suffix_text) <= max_bytes:
            return {"text": suffix_text, "omitted": omitted, "truncated": [], "represented": included}

    if not files:
        return {"text": "", "omitted": [], "truncated": [], "represented": []}

    most_specific = files[-1]
    omitted = [{"absolutePath": f["absolutePath"], "displayPath": f["displayPath"]} for f in files[:-1]]
    original_bytes = byte_length(most_specific["content"])

    for candidate_style in [style, dict(style, intro=COMPACT_WORKSPACE_CONTEXT_INTRO)]:
        truncated_file = truncate_to_fit(most_specific, [], max_bytes, omitted, candidate_style)
        included_bytes = byte_length(truncated_file["content"])
        truncated = [{
            "displayPath": most_specific["displayPath"],
            "originalBytes": original_bytes,
            "includedBytes": included_bytes,
        }]
        text = build_instruction_text([truncated_file], max_bytes, omitted, truncated, candidate_style)
        if byte_length(text) <= max_bytes:
            represented = [most_specific] if (included_bytes > 0 or original_bytes == 0) else []
            return {"text": text, "omitted": omitted, "truncated": truncated, "represented": represented}

    truncated = [{
        "displayPath": most_specific["displayPath"],
        "originalBytes": original_bytes,
        "includedBytes": 0,
    }]
    compact_notice = escape_instruction_frame_body(marker_text(max_bytes, omitted, truncated))
    compact_with_heading = escape_instruction_frame_body(
        "\n\n".join([compact_notice, style["section"](with_truncated_content(most_specific, 0))])
    )
    if byte_length(compact_with_heading) <= max_bytes:
        represented = [most_specific] if original_bytes == 0 else []
        return {"text": compact_with_heading, "omitted": omitted, "truncated": truncated, "represented": represented}

    text = compact_notice if byte_length(compact_notice) <= max_bytes else truncate_utf8(compact_notice, max_bytes)
    return {"text": text, "omitted": omitted, "truncated": truncated, "represented": []}


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
    res = render_instruction_context(files, max_bytes, style)
    represented = res.pop("represented", [])
    return {"rendered": res, "included": represented}


def render_workspace_context(
    files: List[Dict[str, Any]],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    return render_workspace_instruction_set(files, options)["rendered"]


def render_instruction_changes(
    items: List[Dict[str, Any]],
    max_bytes: int,
) -> Dict[str, Any]:
    by_abs_path = {item["file"]["absolutePath"]: item for item in items}

    def custom_section(file_item: Dict[str, Any]) -> str:
        item = by_abs_path.get(file_item["absolutePath"])
        if item is None:
            return ""
        return changed_section_text(dict(item, file=file_item))

    style = {"intro": "", "section": custom_section}
    rendered = render_instruction_context([item["file"] for item in items], max_bytes, style)
    represented = {f["absolutePath"] for f in rendered.get("represented", [])}
    changes = [item["change"] for item in items if item["file"]["absolutePath"] in represented]
    return {"text": rendered["text"], "changes": changes}


def math_is_finite(val: Any) -> bool:
    try:
        import math
        return math.isfinite(val)
    except Exception:
        return True
