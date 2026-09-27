from collections.abc import Mapping
from typing import Any, Dict, List

from dsh.fs.tool_fs_search.search_core import relative_to_search_root, top_level_segment

GLOB_MAX_RESULTS = 100
GLOB_VCS_EXCLUDES = (".git", ".svn", ".hg", ".bzr", ".jj", ".sl")


def parse_glob_args(args: Dict[str, Any]) -> Dict[str, Any]:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")
    path = args.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise ValueError("path must be a non-empty string when given")
    result = {"pattern": pattern}
    if path is not None:
        result["path"] = path
    return result


def build_glob_command(args: Dict[str, Any]) -> List[str]:
    parts = ["--files", "--glob=" + args["pattern"], "--sort=modified",
             "--no-ignore", "--hidden"]
    for name in GLOB_VCS_EXCLUDES:
        parts.extend(("--glob=!**/%s" % name, "--glob=!**/%s/**" % name))
    if args.get("path") is not None:
        parts.extend(("--", args["path"]))
    return parts


def sample_across_top_level(paths: List[str], max_items: int, root: str = ".") -> Dict[str, Any]:
    groups = {}
    active = []
    for path in paths:
        key = top_level_segment(relative_to_search_root(path, root))
        if key not in groups:
            groups[key] = [path]
            active.append({"key": key, "items": groups[key], "index": 0, "current": path})
        else:
            groups[key].append(path)
    taken = {}
    count = 0
    while active and count < max_items:
        next_active = []
        for entry in active:
            if count >= max_items:
                break
            taken.setdefault(entry["key"], []).append(entry["current"])
            count += 1
            index = entry["index"] + 1
            if index < len(entry["items"]):
                next_active.append({"key": entry["key"], "items": entry["items"], "index": index,
                                    "current": entry["items"][index]})
        active = next_active
    items = []
    for bucket in taken.values():
        items.extend(bucket)
    return {"items": items, "shown": len(taken), "total": len(groups)}


def glob_card_page(paths: List[str], max_results: int, sample_over_cap: bool, root: str) -> Dict[str, Any]:
    if len(paths) <= max_results:
        return {"items": paths, "truncated": False, "seen": len(paths)}
    items = sample_across_top_level(paths, max_results, root)["items"] if sample_over_cap else paths[:max_results]
    return {"items": items, "truncated": True, "seen": len(paths)}


def render_glob_paths(paths: List[str], max_results: int, sample_over_cap: bool, root: str,
                      spill_ref: Any = None) -> str:
    if not paths:
        return "No files found"
    if len(paths) <= max_results:
        return "\n".join(paths)
    if sample_over_cap:
        sample = sample_across_top_level(paths, max_results, root)
        basis = ("." if sample["total"] == len(paths) else
                 ", sampled across %d of the %d top-level entries this pattern matched instead of taken in modification-time order." %
                 (sample["shown"], sample["total"]))
        if sample["shown"] < sample["total"]:
            basis += " Narrow path to inspect a specific subtree."
        items = sample["items"]
    else:
        items = paths[:max_results]
        basis = "."
    recovery = ("Full sorted result stored at: %s. %s" %
                (_ref_value(spill_ref, "locator"), _ref_value(spill_ref, "retrievalHint", "retrieval_hint"))
                if spill_ref is not None else
                "The complete result could not be saved; narrow pattern or path to see more.")
    return "%s\n\n(Showing %d of %d paths%s %s)" % (
        "\n".join(items), len(items), len(paths), basis, recovery)


def _ref_value(ref: Any, *names: str) -> Any:
    for name in names:
        if isinstance(ref, Mapping) and name in ref:
            return ref[name]
        if hasattr(ref, name):
            return getattr(ref, name)
    return ""


def present_glob_call(args: Dict[str, Any]) -> Dict[str, Any]:
    where = " in %s" % args["path"] if args.get("path") is not None else ""
    return {"card": "generic", "title": "Glob %s%s" % (args.get("pattern", ""), where),
            "kind": "search", "rawInput": args.get("pattern", "")}


def present_glob_result(_args: Dict[str, Any], result: Any) -> Any:
    if getattr(result, "is_error", getattr(result, "isError", False)):
        return None
    meta = getattr(result, "meta", None)
    if not isinstance(meta, Mapping) or meta.get("shape") != "paths":
        return None
    paths = meta.get("paths")
    if not isinstance(paths, (list, tuple)) or not all(isinstance(path, str) for path in paths):
        return None
    total = meta.get("total")
    if not isinstance(meta.get("truncated"), bool) or isinstance(total, bool) or not isinstance(total, (int, float)):
        return None
    return {"card": "search", "shape": "paths", "paths": list(paths),
            "truncated": meta["truncated"], "total": meta["total"]}
