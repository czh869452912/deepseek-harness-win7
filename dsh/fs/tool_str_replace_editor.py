import asyncio
import inspect
import os
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.fs.fs_local import FsError, FsInfo, FsTarget


TRUNCATED_MESSAGE = (
    "<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with `grep -n` in order to "
    "find the line numbers of what you are looking for.</NOTE>"
)
DEFAULT_DESCRIPTION = (
    "Custom editing tool for viewing, creating and editing files\n"
    "* State is persistent across command calls and discussions with the user\n"
    "* If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep\n"
    "* The `create` command cannot be used if the specified `path` already exists as a file\n"
    "* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`\n\n"
    "Notes for using the `str_replace` command:\n"
    "* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!\n"
    "* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique\n"
    "* The `new_str` parameter should contain the edited lines that should replace the `old_str`"
)


class _LegacyRunContext:
    """Execution carrier for the compatibility-only direct helper."""

    def __init__(self) -> None:
        self.signal = asyncio.Event()
        self.agent = None


def maybe_truncate(content: str, max_chars: int) -> str:
    return content if len(content) <= max_chars else content[:max_chars] + TRUNCATED_MESSAGE


def match_offsets(content: str, search: str) -> List[int]:
    offsets: List[int] = []
    offset = 0
    while True:
        match = content.find(search, offset)
        if match < 0:
            return offsets
        offsets.append(match)
        offset = match + len(search)


def line_numbers_at(content: str, offsets: List[int]) -> List[int]:
    line = 1
    cursor = 0
    result: List[int] = []
    for offset in offsets:
        while cursor < offset:
            if content[cursor] == "\n":
                line += 1
            cursor += 1
        result.append(line)
    return result


def format_file_view(path: str, content: str, max_output_chars: int, view_range: Optional[List[int]] = None) -> str:
    all_lines = content.split("\n")
    lines = all_lines
    initial_line = 1
    final_line: Optional[int] = None
    prompt = "Here's the content of %s with line numbers (which has a total of %d lines)" % (path, len(all_lines))
    if view_range is not None:
        if (not isinstance(view_range, (list, tuple)) or len(view_range) != 2
                or not all(isinstance(item, int) and not isinstance(item, bool) for item in view_range)):
            raise ValueError("Invalid `view_range`. It should be a list of two integers.")
        initial_line, final_line = view_range
        rendered_range = ", ".join(str(item) for item in view_range)
        if initial_line < 1 or initial_line > len(all_lines):
            raise ValueError("Invalid `view_range`: [%s]. Its first element `%s` should be within the range of lines of the file: [1, %d]" % (rendered_range, initial_line, len(all_lines)))
        if final_line > len(all_lines):
            raise ValueError("Invalid `view_range`: [%s]. Its second element `%s` should be smaller than the number of lines in the file: `%d`" % (rendered_range, final_line, len(all_lines)))
        if final_line != -1 and final_line < initial_line:
            raise ValueError("Invalid `view_range`: [%s]. Its second element `%s` should be larger or equal than its first `%s`" % (rendered_range, final_line, initial_line))
        lines = all_lines[initial_line - 1:] if final_line == -1 else all_lines[initial_line - 1:final_line]
        prompt += " with view_range=[%s, %s]" % (initial_line, final_line)
    numbered = "\n".join("%s  %s" % (str(initial_line + index).rjust(6, " "), line) for index, line in enumerate(lines))
    return maybe_truncate("%s:\n%s\n" % (prompt, numbered), max_output_chars)


async def _resolve_target(fs: Any, path: str, signal: Any) -> FsTarget:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    if not os.path.isabs(path):
        raise ValueError("The path %s is not an absolute path, it should start with `/`. Maybe you meant /%s?" % (path, path))
    value = fs.resolve(path, {"signal": signal})
    return await value if inspect.isawaitable(value) else value


async def _stat(fs: Any, target: FsTarget, signal: Any) -> Optional[FsInfo]:
    value = fs.stat(target, signal)
    return await value if inspect.isawaitable(value) else value


async def _stat_existing(ctx: Any, fs: Any, target: FsTarget, command: str,
                         run_context: Any) -> FsInfo:
    info = await _stat(fs, target, run_context.signal)
    if info is None:
        ctx.emit("fs/observed", target, {"kind": "absent"}, run_context)
        raise FsError("The path %s does not exist. Please provide a valid path." % target.displayPath, "FS_NOT_FOUND")
    if info.type == "directory" and command != "view":
        raise FsError("The path %s is a directory and only the `view` command can be used on directories" % target.displayPath, "FS_NOT_REGULAR_FILE")
    return info


async def _list_directory(fs: Any, target: FsTarget, max_output_chars: int,
                          signal: Any) -> str:
    async def visit(directory: FsTarget, depth: int) -> List[str]:
        value = fs.listDir(directory, signal)
        entries = await value if inspect.isawaitable(value) else value
        rows: List[str] = []
        for entry in entries:
            if entry.name.startswith(".") or entry.name in ("node_modules", "__pycache__"):
                continue
            kind = "d" if entry.type == "directory" else ("f" if entry.type == "file" else "?")
            rows.append("%s\t%s" % (kind, entry.target.displayPath))
            if entry.type == "directory" and depth < 2:
                rows.extend(await visit(entry.target, depth + 1))
        return rows
    rows = ["d\t%s" % target.displayPath] + await visit(target, 1)
    rows.sort(key=lambda row: row.split("\t", 1)[1])
    listing = maybe_truncate("\n".join(rows) + "\n", max_output_chars)
    return "Here're the files and directories up to 2 levels deep in %s, excluding hidden items, node_modules, and Python cache directories:\n%s\n" % (target.displayPath, listing)


def _required(value: Optional[str], parameter: str, command: str, allow_empty: bool = True) -> str:
    if value is None:
        raise ValueError("Parameter `%s` is required for command: %s" % (parameter, command))
    if not allow_empty and len(value) == 0:
        raise ValueError("Parameter `%s` is empty for command: %s" % (parameter, command))
    return value


async def _write_text(fs: Any, target: FsTarget, content: str, intent: Any,
                      signal: Any, policy: Any) -> Any:
    try:
        value = fs.writeText(target, content, intent, signal, policy)
        return await value if inspect.isawaitable(value) else value
    except FsError as error:
        if error.code != "FS_SANDBOX_DENIED":
            raise
        mode = policy.get("mode") if isinstance(policy, dict) else getattr(policy, "mode", None)
        raise FsError(
            "[sandbox: file access denied under %s mode]" % mode,
            "FS_SANDBOX_DENIED",
            cause=error,
        )


class StrReplaceEditorPlugin(Plugin):
    id = "str-replace-editor"
    name = "@deepseek-ai/dsh-tool-str-replace-editor"
    inject = ["tools", "fs"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        limit = self.config.get("maxOutputChars", 16000)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 9007199254740991:
            raise ValueError("tool-str-replace-editor: maxOutputChars must be a positive safe integer")
        description = self.config.get("description", DEFAULT_DESCRIPTION)
        if not isinstance(description, str) or not description.strip():
            raise ValueError("tool-str-replace-editor: description must be non-empty")
        self.max_output_chars = limit
        self.description = description

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        fs = ctx.get("fs")
        if getattr(fs, "sandboxMode", None) is not None and not ctx.has("sandboxPolicy"):
            raise RuntimeError("tool-str-replace-editor: the mounted filesystem confines but ctx.sandboxPolicy is missing")
        parameters = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert"], "description": "The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`."},
                "path": {"type": "string", "description": "Absolute path to file or directory, e.g. `/repo/file.py` or `/repo`."},
                "file_text": {"type": "string", "description": "Required parameter of `create` command, with the content of the file to be created."},
                "insert_line": {"type": "integer", "description": "Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`."},
                "new_str": {"type": "string", "description": "Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert."},
                "old_str": {"type": "string", "description": "Required parameter of `str_replace` command containing the string in `path` to replace."},
                "view_range": {"type": "array", "items": {"type": "integer"}, "description": "Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file."},
            },
            "required": ["command", "path"],
        }

        def present_call(args: Dict[str, Any]) -> Dict[str, Any]:
            command, path = args.get("command"), args.get("path", "")
            if command == "view":
                return {"card": "generic", "title": "view %s" % path, "kind": "read", "locations": [{"path": path}]}
            if command == "create":
                return {"card": "diff", "title": "create %s" % path, "diffs": [{"path": path, "oldText": None, "newText": args.get("file_text") if args.get("file_text") is not None else ""}], "locations": [{"path": path}]}
            if command == "str_replace":
                return {"card": "diff", "title": "str_replace %s" % path, "diffs": [{"path": path, "oldText": args.get("old_str") if args.get("old_str") is not None else None, "newText": args.get("new_str") if args.get("new_str") is not None else ""}], "locations": [{"path": path}]}
            location: Dict[str, Any] = {"path": path}
            if args.get("insert_line") is not None:
                location["line"] = max(1, args["insert_line"] + 1)
            return {"card": "generic", "title": "insert %s" % path, "kind": "edit", "locations": [location]}

        async def execute(args: Dict[str, Any], run_context: Any) -> str:
            return await self.execute_editor(
                command=args["command"],
                path=args["path"],
                file_text=args.get("file_text"),
                old_str=args.get("old_str"),
                new_str=args.get("new_str"),
                insert_line=args.get("insert_line"),
                view_range=args.get("view_range"),
                ctx=ctx,
                exec=run_context,
            )

        definition = {
            "name": "str_replace_editor",
            "description": self.description,
            "parameters": parameters,
            "output": {
                "schema": {"type": "string"},
                "render": lambda _args, value: [{"type": "text", "text": value}],
            },
            "execute": execute,
            "presentCall": present_call,
        }
        ctx.effect(lambda: tools.register(definition), label="str_replace_editor registration")

    async def _sandbox_policy(self, ctx: Any, run_context: Any) -> Optional[Any]:
        fs = ctx.get("fs")
        if getattr(fs, "sandboxMode", None) is None:
            return None
        service = ctx.get("sandboxPolicy")
        agent = getattr(run_context, "agent", None)
        request = {} if agent is None else {"session": agent.session}
        value = service.resolve(request)
        return await value if inspect.isawaitable(value) else value

    async def execute_editor(self, command: str, path: str, file_text: Optional[str] = None,
                             old_str: Optional[str] = None, new_str: Optional[str] = None,
                             insert_line: Optional[int] = None, view_range: Optional[List[int]] = None,
                             ctx: Optional[Any] = None, exec: Optional[Any] = None) -> str:
        if ctx is None or not ctx.has("fs"):
            raise FsError("Filesystem service unavailable", "FS_IO_ERROR")
        run_context = exec if exec is not None else _LegacyRunContext()
        fs = ctx.get("fs")
        if command == "view":
            target = await _resolve_target(fs, path, run_context.signal)
            info = await _stat_existing(ctx, fs, target, "view", run_context)
            if info.type == "directory":
                if view_range is not None:
                    raise ValueError("The `view_range` parameter is not allowed when `path` points to a directory.")
                return await _list_directory(fs, target, self.max_output_chars, run_context.signal)
            if info.type != "file":
                raise FsError('cannot view "%s": not a regular file or directory' % target.displayPath, "FS_NOT_REGULAR_FILE")
            value = fs.readText(target, run_context.signal)
            content = await value if inspect.isawaitable(value) else value
            ctx.emit("fs/observed", target, {"kind": "present", "version": info.version}, run_context)
            return format_file_view(target.displayPath, content, self.max_output_chars, view_range)
        if command == "create":
            content = _required(file_text, "file_text", "create")
            policy = await self._sandbox_policy(ctx, run_context)
            target = await _resolve_target(fs, path, run_context.signal)
            if await _stat(fs, target, run_context.signal) is not None:
                raise ValueError("File already exists at: %s. Cannot overwrite files using command `create`." % target.displayPath)
            intent = await ctx.waterfall("fs/write-intent", target, run_context, lambda *_args: {"kind": "createIfAbsent"})
            outcome = await _write_text(fs, target, content, intent, run_context.signal, policy)
            ctx.emit("fs/observed", target, {"kind": "present", "version": outcome.version}, run_context)
            return "New file created successfully at: %s" % target.displayPath
        if command == "str_replace":
            policy = await self._sandbox_policy(ctx, run_context)
            target = await _resolve_target(fs, path, run_context.signal)
            intent = await ctx.waterfall("fs/edit-intent", target, run_context, lambda *_args: None)
            old_value = _required(old_str, "old_str", "str_replace", allow_empty=False)
            replacement = new_str if new_str is not None else ""
            info = await _stat_existing(ctx, fs, target, "str_replace", run_context)
            if info.type != "file":
                raise FsError('cannot edit "%s": not a regular file' % target.displayPath, "FS_NOT_REGULAR_FILE")
            value = fs.readText(target, run_context.signal)
            before = await value if inspect.isawaitable(value) else value
            offsets = match_offsets(before, old_value)
            if not offsets:
                raise FsError("No replacement was performed, old_str `%s` did not appear verbatim in %s." % (old_value, target.displayPath), "FS_EDIT_NOT_FOUND")
            if len(offsets) > 1:
                lines = ", ".join(str(line) for line in line_numbers_at(before, offsets))
                raise FsError("No replacement was performed. Multiple occurrences of old_str `%s` in lines [%s]. Please ensure it is unique" % (old_value, lines), "FS_AMBIGUOUS_EDIT")
            offset = offsets[0]
            expected = {"kind": "replaceIfVersion", "version": info.version if intent is None else intent["version"]}
            outcome = await _write_text(
                fs,
                target,
                before[:offset] + replacement + before[offset + len(old_value):],
                expected,
                run_context.signal,
                policy,
            )
            ctx.emit("fs/observed", target, {"kind": "present", "version": outcome.version}, run_context)
            return "The file %s has been edited successfully." % target.displayPath
        if command == "insert":
            if insert_line is None:
                raise ValueError("Parameter `insert_line` is required for command: insert")
            inserted = _required(new_str, "new_str", "insert")
            policy = await self._sandbox_policy(ctx, run_context)
            target = await _resolve_target(fs, path, run_context.signal)
            intent = await ctx.waterfall("fs/edit-intent", target, run_context, lambda *_args: None)
            info = await _stat_existing(ctx, fs, target, "insert", run_context)
            if info.type != "file":
                raise FsError('cannot insert into "%s": not a regular file' % target.displayPath, "FS_NOT_REGULAR_FILE")
            value = fs.readText(target, run_context.signal)
            before = await value if inspect.isawaitable(value) else value
            lines = before.split("\n")
            if isinstance(insert_line, bool) or not isinstance(insert_line, int) or insert_line < 0 or insert_line > len(lines):
                raise ValueError("Invalid `insert_line` parameter: %s. It should be within the range of lines of the file: [0, %d]" % (insert_line, len(lines)))
            after = "\n".join(lines[:insert_line] + inserted.split("\n") + lines[insert_line:])
            expected = {"kind": "replaceIfVersion", "version": info.version if intent is None else intent["version"]}
            outcome = await _write_text(fs, target, after, expected, run_context.signal, policy)
            ctx.emit("fs/observed", target, {"kind": "present", "version": outcome.version}, run_context)
            return "The file %s has been edited successfully." % target.displayPath
        raise ValueError("Unknown command '%s'" % command)

    def handle_editor(self, *args: Any, **kwargs: Any) -> Any:
        operation = self.execute_editor(*args, **kwargs)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(operation)
        return operation


__all__ = ["DEFAULT_DESCRIPTION", "TRUNCATED_MESSAGE", "StrReplaceEditorPlugin", "format_file_view", "line_numbers_at", "match_offsets", "maybe_truncate"]
