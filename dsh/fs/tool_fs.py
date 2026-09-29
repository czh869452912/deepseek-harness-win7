import inspect
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from dsh.cordis.plugin import Plugin
from dsh.fs.fs_local import FsError, FsTarget


async def _fire_waterfall(ctx: Optional[Any], event_name: str, target: Any, actor: Any, default: Any = None) -> Any:
    """
    Dispatch one single-slot intent waterfall and return the decider's value.

    Matching the reference tool: the bare default is `undefined`, so a tree
    without a policy plugin keeps the provider's unconditional behaviour.
    """
    if not ctx or not hasattr(ctx, "waterfall"):
        return default
    return await ctx.waterfall(event_name, target, actor, lambda: default)


async def _observation_target(fs: Any, file_path: str, actor: Any = None, policy: Any = None) -> FsTarget:
    """
    The exact target the observation events and mutations share.

    One target identity per operation keeps the policy's observed-state key
    (`targetKey`) consistent between the read that records it and the write
    or edit that guards against it.
    """
    agent = getattr(actor, 'agent', None)
    header = getattr(getattr(agent, 'session', None), 'header', None)
    cwd = header.get('cwd') if isinstance(header, dict) else getattr(header, 'cwd', None)
    if policy and policy.get('workspaceRoot'):
        cwd = policy['workspaceRoot']
    elif cwd and (re.search(r'(?:^|[\\/])\.\.(?:[\\/]|$)', cwd) or
                  re.search(r'(?:^|[\\/])\.\.(?:[\\/]|$)', file_path)):
        cwd = os.path.realpath(cwd)
    if hasattr(fs, 'resolve'):
        options = {'signal': getattr(actor, 'signal', None)}
        if cwd is not None:
            options['cwd'] = cwd
        target = fs.resolve(file_path, options)
        return await target if inspect.isawaitable(target) else target
    resolved_path = fs.resolve_path(file_path) if hasattr(fs, "resolve_path") else file_path
    return FsTarget(target_key=resolved_path, display_path=resolved_path)


async def _mutation_policy(ctx: Any, fs: Any, actor: Any) -> Any:
    if getattr(fs, 'sandboxMode', None) is None:
        return None
    policy = ctx.get('sandboxPolicy')
    if policy is None:
        raise RuntimeError('tool-fs: confining filesystem requires sandboxPolicy')
    agent = getattr(actor, 'agent', None)
    value = policy.resolve({'session': agent.session} if agent is not None else {})
    return await value if inspect.isawaitable(value) else value


def _emit_observed(ctx: Optional[Any], target: FsTarget, observation: Dict[str, Any], actor: Any) -> None:
    """Record one authoritative presence/absence observation for the actor."""
    if ctx and hasattr(ctx, "emit"):
        ctx.emit("fs/observed", target, observation, actor)


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
            sp.section({
                "name": "tool:read",
                "text": "Use the read tool — not shell commands like cat — to inspect text files. Results include line numbers. Use offset and limit to continue reading large files.",
                "order": 100,
            })
            sp.section({
                "name": "tool:write",
                "text": "Use the write tool to create files or completely replace file contents. Existing files are overwritten, so read an existing file first (the default fs-observation-policy requires it) and prefer edit for targeted changes.",
                "order": 101,
            })
            sp.section({
                "name": "tool:edit",
                "text": "Use the edit tool for targeted changes to existing UTF-8 text files. It replaces literal old_string with new_string; by default old_string must appear exactly once. If old_string appears multiple times, provide a more specific old_string or set replace_all to true. Read the file first (the default fs-observation-policy requires it), unless you just created or edited it in this session.",
                "order": 102,
            })

        # ----------------------------------------------------
        # 1. READ Tool
        # ----------------------------------------------------
        async def exec_read(
            file_path: str,
            offset: Optional[int] = 1,
            limit: Optional[int] = None,
            exec_input: Optional[Any] = None,
        ) -> str:
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

            target = await _observation_target(fs, file_path, exec_input)
            info = await fs.stat(target) if hasattr(fs, "stat") else None
            if info is None:
                _emit_observed(ctx, target, {"kind": "absent"}, exec_input)
                raise FsError(f"The path {target.displayPath} does not exist.", "FS_NOT_FOUND")

            if info.type != "file":
                raise FsError(f'cannot read "{target.displayPath}": not a regular file', "FS_NOT_REGULAR_FILE")

            content = await fs.readText(target) if hasattr(fs, "readText") else fs.read_text(target.targetKey)
            _emit_observed(ctx, target, {"kind": "present", "version": info.version}, exec_input)

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

            return format_read_output(target.displayPath, off, selected_lines, total_lines)

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
        async def exec_write(
            file_path: str,
            content: str,
            exec_input: Optional[Any] = None,
            signal: Optional[Any] = None,
        ) -> str:
            fs = ctx.get("fs")
            if not fs:
                raise FsError("Filesystem service unavailable", "FS_IO_ERROR")
            if not file_path or not file_path.strip():
                raise ValueError("file_path must be a non-empty string")

            policy = await _mutation_policy(ctx, fs, exec_input)
            target = await _observation_target(fs, file_path, exec_input, policy)
            # Single-slot decision: the policy plugin produces createIfAbsent/
            # replaceIfVersion; the bare default is undefined (unconditional).
            intent = await _fire_waterfall(ctx, "fs/write-intent", target, exec_input)
            options = {'sandbox_policy': policy} if policy is not None else {}
            outcome = await fs.writeText(target, content, intent, signal, **options)
            _emit_observed(ctx, target, {"kind": "present", "version": outcome.version}, exec_input)

            return format_write_output(target.displayPath, outcome.operation)

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
        async def exec_edit(
            file_path: str,
            old_string: str,
            new_string: str,
            replace_all: Optional[bool] = False,
            exec_input: Optional[Any] = None,
            signal: Optional[Any] = None,
        ) -> str:
            fs = ctx.get("fs")
            if not fs:
                raise FsError("Filesystem service unavailable", "FS_IO_ERROR")
            if not file_path or not file_path.strip():
                raise ValueError("file_path must be a non-empty string")
            if not old_string:
                raise ValueError("old_string must be a non-empty string")
            if old_string == new_string:
                raise ValueError("old_string and new_string must differ")

            policy = await _mutation_policy(ctx, fs, exec_input)
            target = await _observation_target(fs, file_path, exec_input, policy)
            # The reference edit does not stat and records no absence: the
            # observed-state record stays whatever the last authoritative
            # observation was, and the provider raises the stale/not-found code
            # from inside the atomic edit's own critical section.
            #
            # Single-slot decision: the policy plugin rejects an unread edit and
            # supplies the observed version as the read-match-write basis.
            intent = await _fire_waterfall(ctx, "fs/edit-intent", target, exec_input)
            r_all = bool(replace_all)
            outcome = await fs.editText(
                target,
                {"oldString": old_string, "newString": new_string, "replaceAll": r_all},
                intent,
                signal,
                **({'sandbox_policy': policy} if policy is not None else {}),
            )
            _emit_observed(ctx, target, {"kind": "present", "version": outcome.version}, exec_input)

            return format_edit_output(target.displayPath, r_all)

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
