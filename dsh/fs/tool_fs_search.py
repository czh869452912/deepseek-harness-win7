"""
File discovery and content search tools: glob and grep (`@deepseek-ai/dsh-tool-fs-search`).
"""

import fnmatch
import os
import re
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


EXCLUDED_DIRS = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl", "__pycache__", ".venv", "node_modules"}


class FsSearchService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.glob_max_results: int = int(cfg.get("globMaxResults", 100))
        self.grep_max_matches: int = int(cfg.get("grepMaxMatches", 250))
        self.grep_max_line_bytes: int = int(cfg.get("grepMaxLineBytes", 2000))

    def glob(self, pattern: str, path: Optional[str] = None, cwd: Optional[str] = None) -> str:
        root_dir = os.path.abspath(path or cwd or os.getcwd())
        if not os.path.exists(root_dir):
            return f"Error: search root '{root_dir}' does not exist"

        matched_files: List[Tuple[float, str]] = []

        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]

            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")

                # Pattern matching: match either basename or rel_path
                if fnmatch.fnmatch(fname, pattern) or fnmatch.fnmatch(rel_path, pattern):
                    try:
                        mtime = os.path.getmtime(full_path)
                    except OSError:
                        mtime = 0
                    matched_files.append((mtime, rel_path))

        # Sort by mtime descending (most recently modified first)
        matched_files.sort(key=lambda x: x[0], reverse=True)

        total_found = len(matched_files)
        displayed = matched_files[: self.glob_max_results]

        if not displayed:
            return "No files found."

        result_lines = [item[1] for item in displayed]
        if total_found > self.glob_max_results:
            result_lines.append(f"\n[Showing {self.glob_max_results} of {total_found} total matches]")

        return "\n".join(result_lines)

    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        include: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> str:
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
                    if include and not fnmatch.fnmatch(fname, include):
                        continue
                    files_to_search.append(os.path.join(dirpath, fname))

        matches_by_file: Dict[str, List[Tuple[int, str]]] = {}
        total_matches = 0

        for fpath in files_to_search:
            if total_matches >= self.grep_max_matches:
                break
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line_no, line in enumerate(f, start=1):
                        if regex.search(line):
                            rel = os.path.relpath(fpath, root_dir).replace("\\", "/")
                            if rel not in matches_by_file:
                                matches_by_file[rel] = []

                            clean_line = line.rstrip("\r\n")
                            if len(clean_line.encode("utf-8")) > self.grep_max_line_bytes:
                                clean_line = clean_line[:500] + " (line truncated)"

                            matches_by_file[rel].append((line_no, clean_line))
                            total_matches += 1

                            if total_matches >= self.grep_max_matches:
                                break
            except Exception:
                continue

        if not matches_by_file:
            return "No matches found."

        output_parts: List[str] = []
        for rel_path, file_matches in matches_by_file.items():
            output_parts.append(f"{rel_path}:")
            for line_no, preview in file_matches:
                output_parts.append(f"  Line {line_no}: {preview}")

        if total_matches >= self.grep_max_matches:
            output_parts.append(f"\n[Limit reached: showing first {self.grep_max_matches} matches]")

        return "\n".join(output_parts)


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
            return self.service.glob(pattern=pattern, path=path)

        async def exec_grep(pattern: str, path: Optional[str] = None, include: Optional[str] = None) -> str:
            return self.service.grep(pattern=pattern, path=path, include=include)

        disposer1 = tools.register_tool({
            "name": "glob",
            "description": "Fast file path discovery tool using glob pattern. Output is sorted by modification time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py', 'src/**/*.ts')"},
                    "path": {"type": "string", "description": "Optional search root directory path"},
                },
                "required": ["pattern"],
            },
            "execute": exec_glob,
        })

        disposer2 = tools.register_tool({
            "name": "grep",
            "description": "Fast regex content search tool over file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression search pattern"},
                    "path": {"type": "string", "description": "Optional file or directory path"},
                    "include": {"type": "string", "description": "Optional file filter (e.g. '*.py')"},
                },
                "required": ["pattern"],
            },
            "execute": exec_grep,
        })

        def cleanup() -> None:
            disposer1()
            disposer2()

        ctx.effect(cleanup)
