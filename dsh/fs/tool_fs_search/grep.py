import json
from collections.abc import Mapping
from typing import Any, Dict, List

GREP_MAX_MATCHES = 250
GREP_MAX_LINE_BYTES = 2000


def validate_include(include: str) -> None:
    if not include.strip():
        raise ValueError("include must be a non-empty glob when given")
    if include.startswith("!"):
        raise ValueError('include must be a positive glob filter; negated patterns ("!\u2026") are not supported')
    depth = 0
    for char in include:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            raise ValueError("include must be one glob, not a comma-separated list (use {a,b} alternation instead)")


def parse_grep_args(args: Dict[str, Any]) -> Dict[str, Any]:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or len(pattern) == 0:
        raise ValueError("pattern must be a non-empty string")
    path = args.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise ValueError("path must be a non-empty string when given")
    include = args.get("include")
    if include is not None:
        validate_include(include)
    result = {"pattern": pattern}
    if path is not None:
        result["path"] = path
    if include is not None:
        result["include"] = include
    return result


def build_grep_command(args: Dict[str, Any]) -> List[str]:
    parts = ["--json", "--regexp=" + args["pattern"]]
    if args.get("include") is not None:
        parts.append("--glob=" + args["include"])
    if args.get("path") is not None:
        parts.extend(("--", args["path"]))
    return parts


def parse_grep_matches(stdout: str) -> List[Dict[str, Any]]:
    matches = []
    for line in stdout.split("\n"):
        if not line:
            continue
        try:
            record = json.loads(line)
        except Exception as error:
            from dsh.fs.tool_fs_search.search_core import SearchError
            raise SearchError("grep received malformed ripgrep --json output (a line is not JSON)",
                              "SEARCH_FAILED") from error
        if not isinstance(record, dict):
            from dsh.fs.tool_fs_search.search_core import SearchError
            raise SearchError("grep received malformed ripgrep --json output (a record is not an object)",
                              "SEARCH_FAILED")
        if record.get("type") != "match":
            continue
        data = record.get("data")
        path = data.get("path") if isinstance(data, dict) else None
        lines = data.get("lines") if isinstance(data, dict) else None
        path_text = path.get("text") if isinstance(path, dict) else None
        line_number = data.get("line_number") if isinstance(data, dict) else None
        if not isinstance(path_text, str) or isinstance(line_number, bool) or not isinstance(line_number, (int, float)):
            from dsh.fs.tool_fs_search.search_core import SearchError
            raise SearchError("grep received malformed ripgrep --json output (a match record is missing path or line number)",
                              "SEARCH_FAILED")
        if not isinstance(lines, dict):
            from dsh.fs.tool_fs_search.search_core import SearchError
            raise SearchError("grep received malformed ripgrep --json output (a match record has no line content)",
                              "SEARCH_FAILED")
        if isinstance(lines.get("text"), str):
            value = lines["text"]
            if value.endswith("\r\n"):
                value = value[:-2]
            elif value.endswith("\n"):
                value = value[:-1]
        elif isinstance(lines.get("bytes"), str):
            value = "(line is not valid UTF-8)"
        else:
            from dsh.fs.tool_fs_search.search_core import SearchError
            raise SearchError("grep received malformed ripgrep --json output (a match record has neither line text nor bytes)",
                              "SEARCH_FAILED")
        matches.append({"path": path_text, "lineNumber": line_number, "line": value})
    return matches


def format_grep_matches(matches: List[Dict[str, Any]]) -> str:
    groups = {}
    order = []
    for match in matches:
        if match["path"] not in groups:
            groups[match["path"]] = []
            order.append(match["path"])
        groups[match["path"]].append(match)
    sections = []
    for path in order:
        rows = [path]
        rows.extend("Line %d: %s" % (item["lineNumber"], item["line"]) for item in groups[path])
        sections.append("\n".join(rows))
    return "\n\n".join(sections)


def render_retained_grep(retained: Dict[str, Any], spill_ref: Any = None) -> str:
    if retained["seen"] == 0:
        return "No matches found"
    header = ("Found %d of %d matches" % (retained["kept"], retained["seen"])
              if retained["truncated"] else
              "Found %d %s" % (retained["seen"], "match" if retained["seen"] == 1 else "matches"))
    output = header + "\n\n" + format_grep_matches(retained["items"])
    if retained["truncated"]:
        if spill_ref is None:
            recovery = "The complete result could not be saved; narrow pattern, path, or include to see more."
        else:
            locator = spill_ref.get("locator") if isinstance(spill_ref, Mapping) else getattr(spill_ref, "locator", "")
            hint = (spill_ref.get("retrievalHint", spill_ref.get("retrieval_hint", ""))
                    if isinstance(spill_ref, Mapping) else
                    getattr(spill_ref, "retrievalHint", getattr(spill_ref, "retrieval_hint", "")))
            recovery = "Full grep result stored at: %s. %s" % (locator, hint)
        output += "\n\n(%s)" % recovery
    return output


def present_grep_call(args: Dict[str, Any]) -> Dict[str, Any]:
    where = " in %s" % args["path"] if args.get("path") is not None else ""
    include = " (%s)" % args["include"] if args.get("include") is not None else ""
    return {"card": "generic", "title": "Grep %s%s%s" % (args.get("pattern", ""), where, include),
            "kind": "search", "rawInput": args.get("pattern", "")}


def present_grep_result(_args: Dict[str, Any], result: Any) -> Any:
    if getattr(result, "is_error", getattr(result, "isError", False)):
        return None
    meta = getattr(result, "meta", None)
    files = meta.get("files") if isinstance(meta, Mapping) else None
    if not isinstance(meta, Mapping) or meta.get("shape") != "matches" or not isinstance(files, (list, tuple)):
        return None
    total = meta.get("total")
    if not isinstance(meta.get("truncated"), bool) or isinstance(total, bool) or not isinstance(total, (int, float)):
        return None
    projected = []
    for file_group in files:
        if not isinstance(file_group, Mapping) or not isinstance(file_group.get("path"), str):
            return None
        matches = file_group.get("matches")
        if not isinstance(matches, (list, tuple)):
            return None
        projected_matches = []
        for match in matches:
            if not isinstance(match, Mapping):
                return None
            line_number = match.get("lineNumber")
            if isinstance(line_number, bool) or not isinstance(line_number, (int, float)) or not isinstance(match.get("line"), str):
                return None
            projected_matches.append({"lineNumber": line_number, "line": match["line"]})
        projected.append({"path": file_group["path"], "matches": projected_matches})
    return {"card": "search", "shape": "matches", "files": projected,
            "truncated": meta["truncated"], "total": meta["total"]}
