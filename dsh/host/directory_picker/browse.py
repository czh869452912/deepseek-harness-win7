"""
Browse Directory Picker (`@deepseek-ai/dsh-host-directory-picker-browse`).
Aligned 1:1 with reference `directory-picker-browse/src/index.ts`.
"""

import os
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.host.directory_picker.base import DirectoryPickerService


class BrowseDirectoryPickerService(DirectoryPickerService):
    """
    Browse directory picker for remote / headless environments.
    """

    def capability(self) -> Dict[str, Any]:
        return {
            "kind": "browse",
            "list": self.list_directory,
            "createDirectory": self.create_directory,
        }

    async def list_directory(self, target_path: Optional[str] = None) -> Dict[str, Any]:
        path = os.path.abspath(target_path or os.path.expanduser("~"))
        home = os.path.abspath(os.path.expanduser("~"))

        # Build crumbs
        crumbs = []
        curr = path
        while True:
            name = os.path.basename(curr) or curr
            crumbs.insert(0, {"name": name, "path": curr.replace("\\", "/"), "hidden": False})
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent

        # Build entries
        entries = []
        try:
            for item in sorted(os.listdir(path)):
                full = os.path.join(path, item)
                if os.path.isdir(full):
                    entries.append({
                        "name": item,
                        "path": full.replace("\\", "/"),
                        "hidden": item.startswith("."),
                    })
        except Exception:
            pass

        return {
            "path": path.replace("\\", "/"),
            "home": home.replace("\\", "/"),
            "crumbs": crumbs,
            "entries": entries,
            "truncated": False,
        }

    async def create_directory(self, parent_path: str, name: str) -> str:
        target = os.path.join(parent_path, name)
        os.makedirs(target, exist_ok=False)
        return os.path.abspath(target).replace("\\", "/")


class BrowseDirectoryPickerPlugin(Plugin):
    id = "host-directory-picker-browse"
    name = "@deepseek-ai/dsh-host-directory-picker-browse"

    def apply(self, ctx: Any) -> None:
        if ctx.get("directoryPicker") is not None:
            return
        try:
            service = BrowseDirectoryPickerService(ctx)
        except RuntimeError as exc:
            if "has been registered" not in str(exc):
                raise
            return
