import os
import pathlib
from typing import Any, Dict, List, Optional, Union


class FsService:
    """
    Filesystem service registered at `ctx.fs`.
    Provides safe workspace filesystem access for Windows 7.
    """

    def __init__(self, cwd: Optional[str] = None):
        self.cwd = os.path.abspath(cwd or os.getcwd())

    def resolve_path(self, path_str: str) -> str:
        """
        Resolve path string into absolute path.
        """
        p = pathlib.Path(path_str)
        if not p.is_absolute():
            p = pathlib.Path(self.cwd) / p
        return str(p.resolve())

    def exists(self, path_str: str) -> bool:
        return os.path.exists(self.resolve_path(path_str))

    def is_file(self, path_str: str) -> bool:
        return os.path.isfile(self.resolve_path(path_str))

    def is_dir(self, path_str: str) -> bool:
        return os.path.isdir(self.resolve_path(path_str))

    def read_text(self, path_str: str, encoding: str = "utf-8") -> str:
        full_path = self.resolve_path(path_str)
        with open(full_path, "r", encoding=encoding, errors="replace") as f:
            return f.read()

    def write_text(self, path_str: str, content: str, encoding: str = "utf-8") -> None:
        full_path = self.resolve_path(path_str)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding=encoding) as f:
            f.write(content)

    def list_dir(self, path_str: str, max_depth: int = 1) -> List[Dict[str, Any]]:
        full_path = self.resolve_path(path_str)
        if not os.path.isdir(full_path):
            raise NotADirectoryError(f"Path is not a directory: {full_path}")

        results = []
        try:
            for item in os.listdir(full_path):
                if item.startswith('.') or item in ('node_modules', '__pycache__', '.venv'):
                    continue
                item_path = os.path.join(full_path, item)
                is_directory = os.path.isdir(item_path)
                results.append({
                    "name": item,
                    "path": item_path,
                    "type": "directory" if is_directory else "file",
                    "size": os.path.getsize(item_path) if not is_directory else 0
                })
        except PermissionError:
            pass
        return results
