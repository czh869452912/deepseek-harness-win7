import inspect
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from dsh.cordis.plugin import Plugin
from dsh.fs.fs_local import FsError, FsTarget


def _fire_waterfall(ctx: Optional[Any], event_name: str, *args: Any) -> Any:
    if not ctx or not hasattr(ctx, "waterfall"):
        return None
    res = ctx.waterfall(event_name, *args)
    if inspect.isawaitable(res):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(res)
        except RuntimeError:
            pass
    return res


def format_read_output(display_path: str, offset: int, lines: List[Tuple[int, str]], total_lines: int, truncated_by_bytes: bool = False) -> str:
    rendered_lines = [
        f"{str(num).rjust(6, ' ')}  {text}"
        for num, text in lines
    ]
    body = "\n".join(rendered_lines)
    trunc_notice = "\n[output truncated by byte limit]" if truncated_by_bytes else ""
    return (
        f"<path>{display_path}</path>\n"
        f"<type>file</type>\n"
        f"<content>\n"
        f"{body}{trunc_notice}\n"
        f"</content>"
    )


def format_write_output(display_path: str, operation: str) -> str:
    verb = "Created" if operation == "create" else "Updated"
    return (
        f"<path>{display_path}</path>\n"
        f"<type>file</type>\n"
        f"<content>\n"
        f"{verb} file\n"
        f"</content>"
    )


def format_edit_output(display_path: str, replace_all: bool) -> str:
    if replace_all:
        return f"The file {display_path} has been updated. All occurrences were successfully replaced."
    return f"The file {display_path} has been updated successfully."


class ToolFsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-fs`: Model-facing read, write, and edit tools over ctx.fs.
    """

    id = "tool-fs"
    name = "@deepseek-ai/dsh-tool-fs"
    inject = ["tools", "fs"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.read_limit: int = int(cfg.get("readLimit", 2000))
        self.read_max_line_length: int = int(cfg.get("readMaxLineLength", 2000))
        self.read_max_bytes: int = int(cfg.get("readMaxBytes", 50000))
        self.read_stream_min_size: int = int(cfg.get("readStreamMinSize", 10 * 1024 * 1024))

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        sp = ctx.get("systemPrompt") if ctx.has("systemPrompt") else (ctx.get("system_prompt") if ctx.has("system_prompt") else None)
        if sp and hasattr(sp, "section"):
            sp.section(
                name="tool:read",
                text="Use the read tool — not shell commands like cat — to inspect text files. Results include line numbers. Use offset and limit to continue reading large files.",
                order=100,
            )
            sp.section(
                name="tool:write",
                text="Use the write tool to create files or completely replace file contents. Existing files are overwritten, so read an existing file first (the default fs-observation-policy requires it) and prefer edit for targeted changes.",
                order=101,
            )
            sp.section(
                name="tool:edit",
                text="Use the edit tool for targeted changes to existing UTF-8 text files. It replaces literal old_string with new_string; by default old_string must appear exactly once. If old_string appears multiple times, provide a more specific old_string or set replace_all to true. Read the file first (the default fs-observation-policy requires it), unless you just created or edited it in this session.",
                order=102,
            )

        # ----------------------------------------------------
        # 1. READ Tool
        # ----------------------------------------------------
        async def exec_read(file_path: str, offset: Optional[int] = 1, limit: Optional[int] = None) -> str:
            fs = ctx.get("fs")
            if not fs:
                raise FsError("Filesystem service unavailable", "FS_IO_ERROR")
            if not file_path or not file_path.strip():
                raise ValueError("file_path must be a non-empty string")

            off = 1 if offset is None else int(offset)
            if off < 1:
                raise ValueError("offset must be a positive integer")

            lim = self.read_limit if limit is None else int(limit)
            if lim < 1:
                raise ValueError("limit must be a positive integer")
            if lim > self.read_limit:
                raise ValueError(f"limit must be less than or equal to {self.read_limit}")

            resolved_path = fs.resolve_path(file_path) if hasattr(fs, "resolve_path") else file_path
            if hasattr(fs, "exists") and not fs.exists(resolved_path):
                if ctx and hasattr(ctx, "emit"):
                    ctx.emit("fs/observed", resolved_path, {"kind": "absent"})
                raise FsError(f"The path {resolved_path} does not exist.", "FS_NOT_FOUND")

            if hasattr(fs, "is_file") and not fs.is_file(resolved_path):
                raise FsError(f'cannot read "{resolved_path}": not a regular file', "FS_NOT_REGULAR_FILE")

            content = fs.read_text(resolved_path) if hasattr(fs, "read_text") else ""
            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": "1"})

            all_lines = content.split("\n")
            total_lines = len(all_lines)

            start_idx = off - 1
            if start_idx >= total_lines:
                selected_lines: List[Tuple[int, str]] = []
            else:
                end_idx = min(start_idx + lim, total_lines)
                selected_lines = [
                    (i + 1, all_lines[i][: self.read_max_line_length])
                    for i in range(start_idx, end_idx)
                ]

            return format_read_output(resolved_path, off, selected_lines, total_lines)

        def present_read_call(args: Dict[str, Any]) -> Dict[str, Any]:
            p = args.get("file_path", "")
            off = args.get("offset", 1)
            lim = args.get("limit")
            window = f" ({off} - {off + lim - 1})" if lim else f" (from line {off})" if off != 1 else ""
            return {
                "card": "generic",
                "title": f"Read {p}{window}",
                "kind": "read",
                "locations": [{"path": p, "line": off}],
            }

        tools.register_tool({
            "name": "read",
            "description": "Read a UTF-8 text file and return line-numbered content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to read, resolved by the filesystem backend.",
                    },
                    "offset": {
                        "type": "number",
                        "description": "1-based first line to return. Defaults to 1.",
                    },
                    "limit": {
                        "type": "number",
                        "description": f"Maximum number of lines to return. Defaults to {self.read_limit}.",
                    },
                },
                "required": ["file_path"],
            },
            "execute": exec_read,
            "presentCall": present_read_call,
            "present_call": present_read_call,
        })

        # ----------------------------------------------------
        # 2. WRITE Tool
        # ----------------------------------------------------
        async def exec_write(file_path: str, content: str) -> str:
            fs = ctx.get("fs")
            if not fs:
                raise FsError("Filesystem service unavailable", "FS_IO_ERROR")
            if not file_path or not file_path.strip():
                raise ValueError("file_path must be a non-empty string")

            resolved_path = fs.resolve_path(file_path) if hasattr(fs, "resolve_path") else file_path
            existing = fs.exists(resolved_path) if hasattr(fs, "exists") else False

            _fire_waterfall(ctx, "fs/write-intent", resolved_path, lambda: {"kind": "createIfAbsent" if not existing else "replaceIfVersion"})

            if hasattr(fs, "write_text"):
                fs.write_text(resolved_path, content)
            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": "1"})

            op = "update" if existing else "create"
            return format_write_output(resolved_path, op)

        def present_write_call(args: Dict[str, Any]) -> Dict[str, Any]:
            p = args.get("file_path", "")
            c = args.get("content", "")
            return {
                "card": "diff",
                "title": f"Write {p}",
                "diffs": [{"path": p, "oldText": None, "newText": c}],
                "locations": [{"path": p}],
            }

        tools.register_tool({
            "name": "write",
            "description": "Create or fully replace a UTF-8 text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to write, resolved by the filesystem backend.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full UTF-8 text content to write.",
                    },
                },
                "required": ["file_path", "content"],
            },
            "execute": exec_write,
            "presentCall": present_write_call,
            "present_call": present_write_call,
        })

        # ----------------------------------------------------
        # 3. EDIT Tool
        # ----------------------------------------------------
        async def exec_edit(file_path: str, old_string: str, new_string: str, replace_all: Optional[bool] = False) -> str:
            fs = ctx.get("fs")
            if not fs:
                raise FsError("Filesystem service unavailable", "FS_IO_ERROR")
            if not file_path or not file_path.strip():
                raise ValueError("file_path must be a non-empty string")
            if not old_string:
                raise ValueError("old_string must be a non-empty string")
            if old_string == new_string:
                raise ValueError("old_string and new_string must differ")

            resolved_path = fs.resolve_path(file_path) if hasattr(fs, "resolve_path") else file_path
            if hasattr(fs, "exists") and not fs.exists(resolved_path):
                if ctx and hasattr(ctx, "emit"):
                    ctx.emit("fs/observed", resolved_path, {"kind": "absent"})
                raise FsError(f'cannot edit "{resolved_path}": file changed since it was read', "FS_STALE_VERSION")

            if hasattr(fs, "is_file") and not fs.is_file(resolved_path):
                raise FsError(f'cannot edit "{resolved_path}": not a regular file', "FS_NOT_REGULAR_FILE")

            _fire_waterfall(ctx, "fs/edit-intent", resolved_path, lambda: None)

            before = fs.read_text(resolved_path) if hasattr(fs, "read_text") else ""
            if old_string not in before:
                raise FsError(f"No replacement was performed, old_str `{old_string}` did not appear verbatim in {resolved_path}.", "FS_EDIT_NOT_FOUND")

            r_all = bool(replace_all)
            if not r_all and before.count(old_string) > 1:
                raise FsError(f"No replacement was performed. Multiple occurrences of old_str `{old_string}`. Please ensure it is unique", "FS_AMBIGUOUS_EDIT")

            after = before.replace(old_string, new_string) if r_all else before.replace(old_string, new_string, 1)
            if hasattr(fs, "write_text"):
                fs.write_text(resolved_path, after)

            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": "1"})

            return format_edit_output(resolved_path, r_all)

        def present_edit_call(args: Dict[str, Any]) -> Dict[str, Any]:
            p = args.get("file_path", "")
            o = args.get("old_string", "")
            n = args.get("new_string", "")
            return {
                "card": "diff",
                "title": f"Edit {p}",
                "diffs": [{"path": p, "oldText": o or None, "newText": n}],
                "locations": [{"path": p}],
            }

        tools.register_tool({
            "name": "edit",
            "description": "Edit an existing UTF-8 text file by replacing literal text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to edit, resolved by the filesystem backend.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Literal text to replace. Must match exactly.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Literal replacement text. Use an empty string to delete the match.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all matches. Defaults to false; when false, old_string must appear exactly once.",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            "execute": exec_edit,
            "presentCall": present_edit_call,
            "present_call": present_edit_call,
        })


__all__ = ["ToolFsPlugin", "format_read_output", "format_write_output", "format_edit_output"]
