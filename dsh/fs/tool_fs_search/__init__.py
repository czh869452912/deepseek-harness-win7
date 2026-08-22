"""
File discovery and content search tools: glob and grep (`@deepseek-ai/dsh-tool-fs-search`).
"""

import fnmatch
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from dsh.cordis.plugin import Plugin
from dsh.fs.tool_fs_search.glob import sample_across_top_level
from dsh.fs.tool_fs_search.grep import validate_include
from dsh.fs.tool_fs_search.search_core import EXCLUDED_DIRS, relative_to_search_root, strip_leading_separators, top_level_segment


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
            file_lines = [f"{rel_path}"]
            for line_no, content in items:
                file_lines.append(f"Line {line_no}: {content}")
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


def present_glob_call(args: Dict[str, Any]) -> Dict[str, Any]:
    pat = args.get("pattern", "")
    p = args.get("path")
    where = f" in {p}" if p else ""
    return {"card": "generic", "title": f"Glob {pat}{where}", "kind": "search", "rawInput": pat}


def present_grep_call(args: Dict[str, Any]) -> Dict[str, Any]:
    pat = args.get("pattern", "")
    p = args.get("path")
    inc = args.get("include")
    where = f" in {p}" if p else ""
    filt = f" ({inc})" if inc else ""
    return {"card": "generic", "title": f"Grep {pat}{where}{filt}", "kind": "search", "rawInput": pat}


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

        sp = ctx.get("systemPrompt") if ctx.has("systemPrompt") else (ctx.get("system_prompt") if ctx.has("system_prompt") else None)
        if sp and hasattr(sp, "section"):
            sp.section(
                name="tool:glob",
                text=(
                    'Use the glob tool — not shell find — to discover files by path pattern. '
                    'A pattern with no "/" matches basenames at any depth, so "*" matches every file in the tree rather than its top level. '
                    'Results are files only, never directories, and include hidden and ignored files: '
                    'a result that fits comes back in modification-time order, while a larger one is sampled across top-level entries, '
                    'so it spans the tree instead of one subtree.'
                ),
                order=103,
            )
            sp.section(
                name="tool:grep",
                text=(
                    'Use the grep tool — not shell grep or rg — to search file contents. '
                    'Use read on a matched file when you need surrounding context.'
                ),
                order=104,
            )

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
                    "pattern": {
                        "type": "string",
                        "description": 'Glob pattern to match file paths against (e.g. "**/*.ts", "src/**/*.test.js"). A pattern with no "/" matches the basename at any depth, so "*" and "*.ts" both search the whole tree; include a separator to anchor the depth.',
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in. Defaults to the session workspace; a relative path resolves against it.",
                    },
                },
                "required": ["pattern"],
            },
            "execute": exec_glob,
            "presentCall": present_glob_call,
            "present_call": present_glob_call,
        })

        disposer2 = tools.register_tool({
            "name": "grep",
            "description": "Search file contents with a regular expression. Returns matching lines with line numbers, grouped by file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression to search for (ripgrep syntax).",
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search. Defaults to the session workspace; a relative path resolves against it.",
                    },
                    "include": {
                        "type": "string",
                        "description": 'One glob filter for which files to search (e.g. "*.ts", "*.{js,jsx}"). Not a list; negation is not supported.',
                    },
                },
                "required": ["pattern"],
            },
            "execute": exec_grep,
            "presentCall": present_grep_call,
            "present_call": present_grep_call,
        })

        def cleanup() -> None:
            disposer1()
            disposer2()

        ctx.effect(cleanup)
