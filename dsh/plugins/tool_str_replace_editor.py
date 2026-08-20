import os
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class StrReplaceEditorPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-str-replace-editor`: Custom editing tool for viewing, creating, and editing files.
    """

    id = "str-replace-editor"
    name = "@deepseek-ai/dsh-tool-str-replace-editor"
    inject = ["tools", "fs"]

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            print("[StrReplaceEditorPlugin Warning] tools service unavailable")
            return

        description = (
            "Custom editing tool for viewing, creating and editing files\n"
            "* State is persistent across command calls and discussions with the user\n"
            "* If `path` is a file, `view` displays result of `cat -n`. If `path` is a directory, `view` lists contents\n"
            "* `create` command creates a new file\n"
            "* `str_replace` replaces exact matching text in `old_str` with `new_str`\n"
            "* `insert` inserts `new_str` at `insert_line`\n"
        )

        parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                    "description": "The command to run: view, create, str_replace, insert, or undo_edit"
                },
                "path": {
                    "type": "string",
                    "description": "Target absolute path to file or directory"
                },
                "file_text": {
                    "type": "string",
                    "description": "Content for create command"
                },
                "old_str": {
                    "type": "string",
                    "description": "Exact target string to be replaced (for str_replace)"
                },
                "new_str": {
                    "type": "string",
                    "description": "Replacement string (for str_replace) or content to insert (for insert)"
                },
                "insert_line": {
                    "type": "integer",
                    "description": "Line number after which to insert text (0 to insert at beginning)"
                },
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of two line numbers [start_line, end_line] for view command"
                }
            },
            "required": ["command", "path"]
        }

        tools_service.register(
            name="str_replace_editor",
            description=description,
            parameters=parameters,
            handler=self.handle_editor
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
        ctx: Optional[Any] = None
    ) -> str:
        fs = ctx.get("fs") if ctx else None
        if not fs:
            return "Error: Filesystem service unavailable"

        resolved_path = fs.resolve_path(path)

        if command == "view":
            if fs.is_dir(resolved_path):
                entries = fs.list_dir(resolved_path)
                lines = [f"Directory listing for {resolved_path}:"]
                for e in entries:
                    lines.append(f"  [{e['type'][0].upper()}] {e['name']}")
                return "\n".join(lines)

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
            numbered = [f"{start + i:6d}  {line}" for i, line in enumerate(view_lines)]
            return f"Here is content of {resolved_path} (lines {start}-{end} of {total}):\n" + "\n".join(numbered)

        elif command == "create":
            if fs.exists(resolved_path):
                return f"Error: File {resolved_path} already exists."
            text_to_write = file_text if file_text is not None else ""
            fs.write_text(resolved_path, text_to_write)
            return f"File created successfully at {resolved_path}"

        elif command == "str_replace":
            if not fs.is_file(resolved_path):
                return f"Error: File {resolved_path} does not exist."
            if old_str is None or new_str is None:
                return "Error: Both `old_str` and `new_str` are required for `str_replace`."

            content = fs.read_text(resolved_path)
            count = content.count(old_str)
            if count == 0:
                return f"Error: `old_str` was not found in {resolved_path}."
            if count > 1:
                return f"Error: `old_str` matches {count} occurrences in {resolved_path}. Include more context to make it unique."

            new_content = content.replace(old_str, new_str, 1)
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

            lines.insert(target_line, new_str)
            fs.write_text(resolved_path, "\n".join(lines))
            return f"Successfully inserted text at line {target_line} in {resolved_path}."

        else:
            return f"Error: Unknown command '{command}'"
