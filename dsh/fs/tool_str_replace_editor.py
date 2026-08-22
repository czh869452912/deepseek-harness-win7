import inspect
import os
from typing import Any, Dict, List, Optional, Tuple
from dsh.cordis.plugin import Plugin

TRUNCATED_MESSAGE = (
    "<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with `grep -n` in order to "
    "find the line numbers of what you are looking for.</NOTE>"
)


def _fire_waterfall(ctx: Optional[Any], event_name: str, *args: Any) -> None:
    if not ctx or not hasattr(ctx, "waterfall"):
        return
    res = ctx.waterfall(event_name, *args)
    if inspect.isawaitable(res):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(res)
        except RuntimeError:
            asyncio.run(res)


DEFAULT_DESCRIPTION = (
    "Custom editing tool for viewing, creating and editing files\n"
    "* State is persistent across command calls and discussions with the user\n"
    "* If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep\n"
    "* The `create` command cannot be used if the specified `path` already exists as a file\n"
    "* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`\n"
    "\n"
    "Notes for using the `str_replace` command:\n"
    "* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!\n"
    "* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique\n"
    "* The `new_str` parameter should contain the edited lines that should replace the `old_str`"
)


def match_offsets(content: str, search: str) -> List[int]:
    offsets: List[int] = []
    offset = 0
    while True:
        pos = content.find(search, offset)
        if pos < 0:
            break
        offsets.append(pos)
        offset = pos + len(search)
    return offsets


def line_numbers_at(content: str, offsets: List[int]) -> List[int]:
    line = 1
    cursor = 0
    lines: List[int] = []
    for off in offsets:
        while cursor < off and cursor < len(content):
            if content[cursor] == "\n":
                line += 1
            cursor += 1
        lines.append(line)
    return lines


def maybe_truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + TRUNCATED_MESSAGE


def format_file_view(
    path: str,
    content: str,
    max_output_chars: int,
    view_range: Optional[List[int]] = None,
) -> str:
    all_lines = content.split("\n")
    initial_line = 1
    final_line: Optional[int] = None
    prompt = f"Here's the content of {path} with line numbers (which has a total of {len(all_lines)} lines)"

    if view_range is not None:
        if not isinstance(view_range, (list, tuple)) or len(view_range) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in view_range):
            raise ValueError("Invalid `view_range`. It should be a list of two integers.")
        range_str = ", ".join(str(x) for x in view_range)
        initial_line, requested_final_line = view_range
        final_line = requested_final_line
        if initial_line < 1 or initial_line > len(all_lines):
            raise ValueError(
                f"Invalid `view_range`: [{range_str}]. Its first element `{initial_line}` should be within the range of lines of the file: [1, {len(all_lines)}]"
            )
        if final_line != -1 and final_line > len(all_lines):
            raise ValueError(
                f"Invalid `view_range`: [{range_str}]. Its second element `{final_line}` should be smaller than the number of lines in the file: `{len(all_lines)}`"
            )
        if final_line != -1 and final_line < initial_line:
            raise ValueError(
                f"Invalid `view_range`: [{range_str}]. Its second element `{final_line}` should be larger or equal than its first `{initial_line}`"
            )

        if final_line == -1:
            lines = all_lines[initial_line - 1 :]
        else:
            lines = all_lines[initial_line - 1 : final_line]
        prompt += f" with view_range=[{initial_line}, {final_line}]"
    else:
        lines = all_lines

    numbered = [
        f"{str(initial_line + index).rjust(6, ' ')}  {line}"
        for index, line in enumerate(lines)
    ]
    return maybe_truncate(f"{prompt}:\n" + "\n".join(numbered) + "\n", max_output_chars)


def list_directory(
    root_dir: str,
    max_output_chars: int,
) -> str:
    rows: List[str] = [f"d\t{root_dir}"]

    def visit(current_dir: str, depth: int) -> List[str]:
        sub_rows: List[str] = []
        try:
            entries = sorted(os.listdir(current_dir))
        except OSError:
            return sub_rows

        for entry in entries:
            if entry.startswith(".") or entry == "node_modules" or entry == "__pycache__":
                continue
            entry_path = os.path.join(current_dir, entry)
            is_dir = os.path.isdir(entry_path)
            t = "d" if is_dir else ("f" if os.path.isfile(entry_path) else "?")
            sub_rows.append(f"{t}\t{entry_path}")
            if is_dir and depth < 2:
                sub_rows.extend(visit(entry_path, depth + 1))
        return sub_rows

    rows.extend(visit(root_dir, 1))
    rows.sort(key=lambda x: x[x.find("\t") + 1 :])
    listing = maybe_truncate("\n".join(rows) + "\n", max_output_chars)
    return (
        f"Here're the files and directories up to 2 levels deep in {root_dir}, "
        f"excluding hidden items, node_modules, and Python cache directories:\n{listing}\n"
    )


class StrReplaceEditorPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-str-replace-editor`: Custom editing tool for viewing, creating, and editing files.
    """

    id = "str-replace-editor"
    name = "@deepseek-ai/dsh-tool-str-replace-editor"
    inject = ["tools", "fs"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.max_output_chars: int = int(self.config.get("maxOutputChars", 16000))
        self.description: str = str(self.config.get("description", DEFAULT_DESCRIPTION))

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            return

        parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert"],
                    "description": "The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`.",
                },
                "path": {
                    "type": "string",
                    "description": "Absolute path to file or directory, e.g. `/repo/file.py` or `/repo`.",
                },
                "file_text": {
                    "type": "string",
                    "description": "Required parameter of `create` command, with the content of the file to be created.",
                },
                "insert_line": {
                    "type": "integer",
                    "description": "Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.",
                },
                "new_str": {
                    "type": "string",
                    "description": "Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert.",
                },
                "old_str": {
                    "type": "string",
                    "description": "Required parameter of `str_replace` command containing the string in `path` to replace.",
                },
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file.",
                },
            },
            "required": ["command", "path"],
        }

        async def exec_editor(
            command: str,
            path: str,
            file_text: Optional[str] = None,
            old_str: Optional[str] = None,
            new_str: Optional[str] = None,
            insert_line: Optional[int] = None,
            view_range: Optional[List[int]] = None,
        ) -> str:
            return self.handle_editor(
                command=command,
                path=path,
                file_text=file_text,
                old_str=old_str,
                new_str=new_str,
                insert_line=insert_line,
                view_range=view_range,
                ctx=ctx,
            )

        def present_editor_call(args: Dict[str, Any]) -> Dict[str, Any]:
            cmd = args.get("command")
            p = args.get("path", "")
            if cmd == "view":
                return {
                    "card": "generic",
                    "title": f"view {p}",
                    "kind": "read",
                    "locations": [{"path": p}],
                }
            elif cmd == "create":
                file_text = args.get("file_text")
                return {
                    "card": "diff",
                    "title": f"create {p}",
                    "diffs": [{"path": p, "oldText": None, "newText": file_text if file_text is not None else ""}],
                    "locations": [{"path": p}],
                }
            elif cmd == "str_replace":
                new_str = args.get("new_str")
                return {
                    "card": "diff",
                    "title": f"str_replace {p}",
                    "diffs": [{
                        "path": p,
                        "oldText": args.get("old_str"),
                        "newText": new_str if new_str is not None else "",
                    }],
                    "locations": [{"path": p}],
                }
            elif cmd == "insert":
                loc: Dict[str, Any] = {"path": p}
                il = args.get("insert_line")
                if il is not None:
                    loc["line"] = max(1, il + 1)
                return {
                    "card": "generic",
                    "title": f"insert {p}",
                    "kind": "edit",
                    "locations": [loc],
                }
            return {"card": "generic", "title": f"{cmd} {p}"}

        tools_service.register(
            name="str_replace_editor",
            description=self.description,
            parameters=parameters,
            handler=self.handle_editor,
            present_call=present_editor_call,
        )

    def _resolve_target(self, fs: Any, path: str) -> Tuple[Optional[str], Optional[str]]:
        """Mirror TS resolveTarget: non-empty + absolute-path enforcement."""
        if not path or not isinstance(path, str) or not path.strip():
            return None, "Error: path must be a non-empty string"
        if not os.path.isabs(path):
            return None, (
                f"Error: The path {path} is not an absolute path, it should start with `/`. "
                f"Maybe you meant /{path}?"
            )
        return fs.resolve_path(path), None

    def handle_editor(
        self,
        command: str,
        path: str,
        file_text: Optional[str] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        insert_line: Optional[int] = None,
        view_range: Optional[List[int]] = None,
        ctx: Optional[Any] = None,
    ) -> str:
        fs = ctx.get("fs") if ctx else None
        if not fs:
            return "Error: Filesystem service unavailable"

        if command == "view":
            resolved_path, err = self._resolve_target(fs, path)
            if err:
                return err
            display_path = resolved_path

            if not fs.exists(resolved_path):
                if ctx and hasattr(ctx, "emit"):
                    ctx.emit("fs/observed", resolved_path, {"kind": "absent"})
                return f"Error: The path {display_path} does not exist. Please provide a valid path."

            if fs.is_dir(resolved_path):
                if view_range is not None:
                    return "Error: The `view_range` parameter is not allowed when `path` points to a directory."
                return list_directory(resolved_path, self.max_output_chars)

            if not fs.is_file(resolved_path):
                return f"Error: cannot view \"{display_path}\": not a regular file or directory"

            content = fs.read_text(resolved_path)
            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": 1})
            try:
                return format_file_view(display_path, content, self.max_output_chars, view_range)
            except ValueError as ve:
                return f"Error: {ve}"

        elif command == "create":
            if file_text is None:
                return "Error: Parameter `file_text` is required for command: create"
            resolved_path, err = self._resolve_target(fs, path)
            if err:
                return err
            display_path = resolved_path

            if fs.exists(resolved_path):
                return f"Error: File already exists at: {display_path}. Cannot overwrite files using command `create`."

            _fire_waterfall(ctx, "fs/write-intent", resolved_path, lambda: {"kind": "createIfAbsent"})

            fs.write_text(resolved_path, file_text)
            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": 1})
            return f"New file created successfully at: {display_path}"

        elif command == "str_replace":
            resolved_path, err = self._resolve_target(fs, path)
            if err:
                return err
            display_path = resolved_path

            _fire_waterfall(ctx, "fs/edit-intent", resolved_path, lambda: None)

            if old_str is None:
                return "Error: Parameter `old_str` is required for command: str_replace"
            if len(old_str) == 0:
                return "Error: Parameter `old_str` is empty for command: str_replace"
            replacement = new_str if new_str is not None else ""

            if not fs.exists(resolved_path):
                if ctx and hasattr(ctx, "emit"):
                    ctx.emit("fs/observed", resolved_path, {"kind": "absent"})
                return f"Error: The path {display_path} does not exist. Please provide a valid path."
            if fs.is_dir(resolved_path):
                return f"Error: The path {display_path} is a directory and only the `view` command can be used on directories"
            if not fs.is_file(resolved_path):
                return f"Error: cannot edit \"{display_path}\": not a regular file"

            content = fs.read_text(resolved_path)
            offsets = match_offsets(content, old_str)
            count = len(offsets)

            if count == 0:
                return f"Error: No replacement was performed, old_str `{old_str}` did not appear verbatim in {display_path}."
            if count > 1:
                lines = line_numbers_at(content, offsets)
                lines_str = ", ".join(str(l) for l in lines)
                return f"Error: No replacement was performed. Multiple occurrences of old_str `{old_str}` in lines [{lines_str}]. Please ensure it is unique"

            new_content = content[: offsets[0]] + replacement + content[offsets[0] + len(old_str) :]
            fs.write_text(resolved_path, new_content)
            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": 1})
            return f"The file {display_path} has been edited successfully."

        elif command == "insert":
            if insert_line is None:
                return "Error: Parameter `insert_line` is required for command: insert"
            if new_str is None:
                return "Error: Parameter `new_str` is required for command: insert"

            resolved_path, err = self._resolve_target(fs, path)
            if err:
                return err
            display_path = resolved_path

            _fire_waterfall(ctx, "fs/edit-intent", resolved_path, lambda: None)

            if not fs.exists(resolved_path):
                if ctx and hasattr(ctx, "emit"):
                    ctx.emit("fs/observed", resolved_path, {"kind": "absent"})
                return f"Error: The path {display_path} does not exist. Please provide a valid path."
            if fs.is_dir(resolved_path):
                return f"Error: The path {display_path} is a directory and only the `view` command can be used on directories"
            if not fs.is_file(resolved_path):
                return f"Error: cannot insert into \"{display_path}\": not a regular file"

            content = fs.read_text(resolved_path)
            lines = content.split("\n")
            if not isinstance(insert_line, int) or isinstance(insert_line, bool) or insert_line < 0 or insert_line > len(lines):
                return f"Error: Invalid `insert_line` parameter: {insert_line}. It should be within the range of lines of the file: [0, {len(lines)}]"

            inserted_lines = new_str.split("\n")
            after_lines = lines[:insert_line] + inserted_lines + lines[insert_line:]
            fs.write_text(resolved_path, "\n".join(after_lines))
            if ctx and hasattr(ctx, "emit"):
                ctx.emit("fs/observed", resolved_path, {"kind": "present", "version": 1})
            return f"The file {display_path} has been edited successfully."

        else:
            return f"Error: Unknown command '{command}'"


