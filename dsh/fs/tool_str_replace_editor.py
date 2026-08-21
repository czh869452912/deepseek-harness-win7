import os
from typing import Any, Dict, List, Optional, Tuple
from dsh.cordis.plugin import Plugin

TRUNCATED_MESSAGE = (
    "\n<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with `grep -n` in order to "
    "find the line numbers of what you are looking for.</NOTE>"
)

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


def list_dir_2_levels(root_dir: str) -> List[str]:
    entries: List[str] = []
    try:
        top_items = sorted(os.listdir(root_dir))
        for item in top_items:
            if item.startswith("."):
                continue
            item_path = os.path.join(root_dir, item)
            is_directory = os.path.isdir(item_path)
            prefix = "[D] " if is_directory else "[F] "
            entries.append(f"  {prefix}{item}")

            if is_directory:
                try:
                    sub_items = sorted(os.listdir(item_path))
                    for sub in sub_items:
                        if sub.startswith("."):
                            continue
                        sub_path = os.path.join(item_path, sub)
                        sub_prefix = "[D] " if os.path.isdir(sub_path) else "[F] "
                        entries.append(f"    {sub_prefix}{sub}")
                except OSError:
                    pass
    except OSError as e:
        entries.append(f"  (Error listing directory: {e})")
    return entries


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
        self._undo_history: Dict[str, str] = {}

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            print("[StrReplaceEditorPlugin Warning] tools service unavailable")
            return

        parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                    "description": "The command to run: view, create, str_replace, insert, or undo_edit",
                },
                "path": {
                    "type": "string",
                    "description": "Target absolute path to file or directory",
                },
                "file_text": {
                    "type": "string",
                    "description": "Content for create command",
                },
                "old_str": {
                    "type": "string",
                    "description": "Exact target string to be replaced (for str_replace)",
                },
                "new_str": {
                    "type": "string",
                    "description": "Replacement string (for str_replace) or content to insert (for insert)",
                },
                "insert_line": {
                    "type": "integer",
                    "description": "Line number after which to insert text (0 to insert at beginning)",
                },
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of two line numbers [start_line, end_line] for view command",
                },
            },
            "required": ["command", "path"],
        }

        tools_service.register(
            name="str_replace_editor",
            description=DEFAULT_DESCRIPTION,
            parameters=parameters,
            handler=self.handle_editor,
        )

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

        if not path or not path.strip():
            return "Error: path must be a non-empty string"

        resolved_path = fs.resolve_path(path)

        if command == "view":
            if fs.is_dir(resolved_path):
                entries = list_dir_2_levels(resolved_path)
                header = f"Directory listing for {resolved_path} (up to 2 levels deep):"
                content = header + "\n" + "\n".join(entries)
                return maybe_truncate(content, self.max_output_chars)

            if not fs.is_file(resolved_path):
                return f"Error: Path {resolved_path} does not exist."

            content = fs.read_text(resolved_path)
            lines = content.split("\n")
            total = len(lines)

            start = 1
            end = total
            if view_range and len(view_range) == 2:
                start = max(1, view_range[0])
                if view_range[1] != -1:
                    end = min(total, view_range[1])

            view_lines = lines[start - 1 : end]
            numbered = [f"{start + i:6d}\t{line}" for i, line in enumerate(view_lines)]
            rendered = f"Here is content of {resolved_path} (lines {start}-{end} of {total}):\n" + "\n".join(numbered)
            return maybe_truncate(rendered, self.max_output_chars)

        elif command == "create":
            if fs.exists(resolved_path):
                return f"Error: File {resolved_path} already exists."
            text_to_write = file_text if file_text is not None else ""
            fs.write_text(resolved_path, text_to_write)
            self._undo_history[resolved_path] = ""
            return f"File created successfully at {resolved_path}"

        elif command == "str_replace":
            if not fs.is_file(resolved_path):
                return f"Error: File {resolved_path} does not exist."
            if old_str is None or new_str is None:
                return "Error: Both `old_str` and `new_str` are required for `str_replace`."

            content = fs.read_text(resolved_path)
            offsets = match_offsets(content, old_str)
            count = len(offsets)

            if count == 0:
                return f"Error: `old_str` was not found in {resolved_path}."
            if count > 1:
                lines = line_numbers_at(content, offsets)
                lines_str = ", ".join(str(l) for l in lines)
                return f"Error: `old_str` matches {count} occurrences in {resolved_path} at lines {lines_str}. Include more context to make it unique."

            self._undo_history[resolved_path] = content

            new_content = content[: offsets[0]] + new_str + content[offsets[0] + len(old_str) :]
            fs.write_text(resolved_path, new_content)
            return f"Successfully replaced content in {resolved_path}."

        elif command == "insert":
            if not fs.is_file(resolved_path):
                return f"Error: File {resolved_path} does not exist."
            if new_str is None:
                return "Error: `new_str` is required for `insert`."
            target_line = insert_line if insert_line is not None else 0

            content = fs.read_text(resolved_path)
            lines = content.split("\n")
            if target_line < 0 or target_line > len(lines):
                return f"Error: `insert_line` {target_line} is out of bounds (file has {len(lines)} lines)."

            self._undo_history[resolved_path] = content

            lines.insert(target_line, new_str)
            fs.write_text(resolved_path, "\n".join(lines))
            return f"Successfully inserted text at line {target_line} in {resolved_path}."

        elif command == "undo_edit":
            if resolved_path not in self._undo_history:
                return f"Error: No edit history found for {resolved_path} to undo."

            prev_content = self._undo_history.pop(resolved_path)
            if prev_content == "":
                if fs.exists(resolved_path):
                    fs.write_text(resolved_path, "")
                return f"Successfully reverted creation of {resolved_path}."
            else:
                fs.write_text(resolved_path, prev_content)
                return f"Successfully reverted changes to {resolved_path}."

        else:
            return f"Error: Unknown command '{command}'"

