"""
File discovery and content search tools: glob and grep (`@deepseek-ai/dsh-tool-fs-search`).
"""

import fnmatch
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from dsh.cordis.plugin import Plugin


EXCLUDED_DIRS = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl", "__pycache__", ".venv", "node_modules"}


def strip_leading_separators(path: str) -> str:
    start = 0
    while start < len(path) and path[start] in ("/", "\\"):
        start += 1
    return path[start:]


def top_level_segment(path: str) -> str:
    trimmed = strip_leading_separators(path)
    cut_fwd = trimmed.find("/")
    cut_back = trimmed.find("\\")
    cut = min([c for c in [cut_fwd, cut_back] if c != -1], default=-1)
    return trimmed[:cut] if cut != -1 else trimmed


def relative_to_search_root(path: str, root: str) -> str:
    if root in (".", "./", ".\\"):
        return path[2:] if path.startswith(("./", ".\\")) else path
    trimmed_root = root.rstrip("/\\")
    if not trimmed_root:
        return strip_leading_separators(path)
    if path == trimmed_root:
        return ""
    if path.startswith(trimmed_root + "/") or path.startswith(trimmed_root + "\\"):
        return path[len(trimmed_root) + 1 :]
    return path


def sample_across_top_level(paths: List[str], max_items: int, root: str = ".") -> Dict[str, Any]:
    groups: Dict[str, List[str]] = {}
    active: List[Dict[str, Any]] = []

    for p in paths:
        rel = relative_to_search_root(p, root)
        key = top_level_segment(rel)
        if key not in groups:
            groups[key] = [p]
            active.append({"key": key, "items": groups[key], "index": 0, "current": p})
        else:
            groups[key].append(p)

    taken: Dict[str, List[str]] = {}
    count = 0

    while active and count < max_items:
        next_active = []
        for entry in active:
            if count >= max_items:
                break
            key = entry["key"]
            current = entry["current"]
            count += 1
            if key not in taken:
                taken[key] = [current]
            else:
                taken[key].append(current)

            next_index = entry["index"] + 1
            items = entry["items"]
            if next_index < len(items):
                next_active.append({
                    "key": key,
                    "items": items,
                    "index": next_index,
                    "current": items[next_index],
                })
        active = next_active

    flat_items: List[str] = []
    for bucket in taken.values():
        flat_items.extend(bucket)

    return {
        "items": flat_items,
        "shown": len(taken),
        "total": len(groups),
    }


def validate_include(include: str) -> None:
    trimmed = include.strip()
    if not trimmed:
        raise ValueError("include must be a non-empty glob when given")
    if trimmed.startswith("!"):
        raise ValueError('include must be a positive glob filter; negated patterns ("!…") are not supported')
    brace_depth = 0
    for char in trimmed:
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "," and brace_depth == 0:
            raise ValueError("include must be one glob, not a comma-separated list (use {a,b} alternation instead)")


class FsSearchService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.sample_over_cap_glob: bool = bool(cfg.get("sampleOverCapGlobResults", True))
        self.glob_max_results: int = int(cfg.get("globMaxResults", 100))
        self.grep_max_matches: int = int(cfg.get("grepMaxMatches", 250))
        self.grep_max_line_bytes: int = int(cfg.get("grepMaxLineBytes", 2000))

    def glob(self, pattern: str, path: Optional[str] = None, cwd: Optional[str] = None, ctx: Optional[Any] = None) -> str:
        if not pattern or not pattern.strip():
            return "Error: pattern must be a non-empty string"
        if path is not None and not path.strip():
            return "Error: path must be a non-empty string when given"

        search_root = path or cwd or os.getcwd()
        root_dir = os.path.abspath(search_root)
        if not os.path.exists(root_dir):
            return f"Error: search root '{root_dir}' does not exist"

        matched_files: List[Tuple[float, str]] = []

        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]

            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")

                if fnmatch.fnmatch(fname, pattern) or fnmatch.fnmatch(rel_path, pattern):
                    try:
                        mtime = os.path.getmtime(full_path)
                    except OSError:
                        mtime = 0
                    matched_files.append((mtime, rel_path))

        matched_files.sort(key=lambda x: x[0], reverse=True)

        if not matched_files:
            return "No files found"

        all_paths = [item[1] for item in matched_files]
        total_found = len(all_paths)

        spill_ref = None
        spill_store = ctx.get("spillStore") if ctx and hasattr(ctx, "get") else None
        if total_found > self.glob_max_results and spill_store:
            try:
                spill_ref = spill_store.save_text("\n".join(all_paths), prefix="glob-result")
            except Exception:
                pass

        if total_found <= self.glob_max_results:
            return "\n".join(all_paths)

        recovery = (
            f"Full sorted result stored at: {spill_ref.locator}. {spill_ref.retrieval_hint}"
            if spill_ref
            else "The complete result could not be saved; narrow pattern or path to see more."
        )

        if not self.sample_over_cap_glob:
            displayed = all_paths[: self.glob_max_results]
            body = "\n".join(displayed)
            footer = f"\n\n(Showing {len(displayed)} of {total_found} paths. {recovery})"
            return body + footer

        sample = sample_across_top_level(all_paths, self.glob_max_results, root=".")
        body = "\n".join(sample["items"])
        basis = (
            "."
            if sample["total"] == total_found
            else f", sampled across {sample['shown']} of the {sample['total']} top-level entries this pattern matched instead of taken in modification-time order."
        )
        narrow_hint = " Narrow path to inspect a specific subtree." if sample["shown"] < sample["total"] else ""
        footer = f"\n\n(Showing {len(sample['items'])} of {total_found} paths{basis}{narrow_hint} {recovery})"
        return body + footer

    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        include: Optional[str] = None,
        cwd: Optional[str] = None,
        ctx: Optional[Any] = None,
    ) -> str:
        if pattern is None or len(pattern) == 0:
            return "Error: pattern must be a non-empty string"
        if path is not None and not path.strip():
            return "Error: path must be a non-empty string when given"
        if include is not None:
            try:
                validate_include(include)
            except ValueError as ve:
                return f"Error: {ve}"

        target_path = os.path.abspath(path or cwd or os.getcwd())
        if not os.path.exists(target_path):
            return f"Error: target '{target_path}' does not exist"

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regex pattern '{pattern}': {e}"

        files_to_search: List[str] = []
        if os.path.isfile(target_path):
            files_to_search.append(target_path)
            root_dir = os.path.dirname(target_path)
        else:
            root_dir = target_path
            for dirpath, dirnames, filenames in os.walk(target_path):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
                for fname in filenames:
                    if include:
                        if not fnmatch.fnmatch(fname, include):
                            continue
                    files_to_search.append(os.path.join(dirpath, fname))

        matches_by_file: Dict[str, List[Tuple[int, str]]] = {}
        total_matches = 0

        for fpath in files_to_search:
            if total_matches >= self.grep_max_matches:
                break
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()

                file_matches: List[Tuple[int, str]] = []
                for idx, line in enumerate(lines, start=1):
                    if regex.search(line):
                        clean_line = line.rstrip("\r\n")
                        line_bytes = clean_line.encode("utf-8")
                        if len(line_bytes) > self.grep_max_line_bytes:
                            clean_line = clean_line[:500] + " (line truncated)"

                        file_matches.append((idx, clean_line))
                        total_matches += 1
                        if total_matches >= self.grep_max_matches:
                            break

                if file_matches:
                    rel = os.path.relpath(fpath, root_dir).replace("\\", "/")
                    matches_by_file[rel] = file_matches

            except Exception:
                continue

        if not matches_by_file:
            return "No matches found"

        noun = "match" if total_matches == 1 else "matches"
        header = f"Found {total_matches} {noun}"

        sections: List[str] = [header]
        for rel_path, items in matches_by_file.items():
            file_lines = [f"{rel_path}:"]
            for line_no, content in items:
                file_lines.append(f"  Line {line_no}: {content}")
            sections.append("\n".join(file_lines))

        spill_ref = None
        spill_store = ctx.get("spillStore") if ctx and hasattr(ctx, "get") else None
        if total_matches >= self.grep_max_matches:
            if spill_store:
                try:
                    spill_ref = spill_store.save_text("\n\n".join(sections), prefix="grep-result")
                except Exception:
                    pass

            recovery = (
                f"Full result stored at: {spill_ref.locator}. {spill_ref.retrieval_hint}"
                if spill_ref
                else "Narrow pattern, path, or include to see more."
            )
            sections.append(f"\n(Showing {total_matches} matches. {recovery})")

        return "\n\n".join(sections).strip()


class ToolFsSearchPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-fs-search`: Exposes glob and grep file discovery tools.
    """

    id = "tool-fs-search"
    name = "@deepseek-ai/dsh-tool-fs-search"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.service = FsSearchService(config)

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        async def exec_glob(pattern: str, path: Optional[str] = None) -> str:
            return self.service.glob(pattern=pattern, path=path, ctx=ctx)

        async def exec_grep(
            pattern: str,
            path: Optional[str] = None,
            include: Optional[str] = None,
        ) -> str:
            return self.service.grep(
                pattern=pattern,
                path=path,
                include=include,
                ctx=ctx,
            )

        disposer1 = tools.register_tool({
            "name": "glob",
            "description": "Find files whose paths match a glob pattern. Returns matching file paths — never directories — including hidden and ignored files. Results come back in modification-time order or top-level sampled when large.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "The glob pattern to match against paths."},
                    "path": {"type": "string", "description": "The directory to search in. Defaults to the current working directory."},
                },
                "required": ["pattern"],
            },
            "execute": exec_glob,
        })

        disposer2 = tools.register_tool({
            "name": "grep",
            "description": "Search file contents with a regular expression. Returns matching lines with line numbers, grouped by file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "The regular expression pattern to match in file contents."},
                    "path": {"type": "string", "description": "The directory or file to search in. Defaults to the current working directory."},
                    "include": {"type": "string", "description": "A glob pattern to filter files that are searched (e.g. '*.ts')."},
                },
                "required": ["pattern"],
            },
            "execute": exec_grep,
        })

        def cleanup() -> None:
            disposer1()
            disposer2()

        ctx.effect(cleanup)


