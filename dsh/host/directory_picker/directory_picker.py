"""
Host Directory Picker capability seam and services.
Aligned 1:1 with `@deepseek-ai/dsh-host-directory-picker`, `@deepseek-ai/dsh-host-directory-picker-auto`,
`@deepseek-ai/dsh-host-directory-picker-native`, and `@deepseek-ai/dsh-host-directory-picker-browse`.
"""

import asyncio
import os
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class DirectoryPickerService:
    """
    Abstract directory picker service definition on ctx.directoryPicker.
    """

    name = "directoryPicker"

    def __init__(self, ctx: Any):
        self.ctx = ctx
        ctx.set_service("directory_picker", self)
        ctx.set_service("directoryPicker", self)

    def capability(self) -> Dict[str, Any]:
        raise NotImplementedError


class NativeDirectoryPickerService(DirectoryPickerService):
    """
    Native directory chooser on host display.
    """

    def capability(self) -> Dict[str, Any]:
        return {
            "kind": "native",
            "pick": self.pick_native,
        }

    async def pick_native(self) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._pick_native_sync)

    def _pick_native_sync(self) -> Optional[str]:
        # Try Python standard library tkinter first (zero external dependencies)
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(title="Select Workspace Directory")
            root.destroy()
            return os.path.normpath(selected) if selected else None
        except Exception:
            pass

        # Fallback to PowerShell FolderBrowserDialog on Windows
        if sys.platform == "win32" or os.name == "nt":
            try:
                ps_script = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                    "$f.Description = 'Select Workspace Directory'; "
                    "$f.ShowNewFolderButton = $true; "
                    "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
                )
                res = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                out = res.stdout.strip()
                return os.path.normpath(out) if out else None
            except Exception:
                pass

        return None


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
            crumbs.insert(0, {"name": name, "path": curr, "hidden": False})
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
                        "path": full,
                        "hidden": item.startswith("."),
                    })
        except Exception:
            pass

        return {
            "path": path,
            "home": home,
            "crumbs": crumbs,
            "entries": entries,
            "truncated": False,
        }

    async def create_directory(self, parent_path: str, name: str) -> str:
        target = os.path.join(parent_path, name)
        os.makedirs(target, exist_ok=False)
        return os.path.abspath(target)


class NativeDirectoryPickerPlugin(Plugin):
    id = "host-directory-picker-native"
    name = "@deepseek-ai/dsh-host-directory-picker-native"

    def apply(self, ctx: Any) -> None:
        service = NativeDirectoryPickerService(ctx)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: ctx.set_service("directoryPicker", None))


class BrowseDirectoryPickerPlugin(Plugin):
    id = "host-directory-picker-browse"
    name = "@deepseek-ai/dsh-host-directory-picker-browse"

    def apply(self, ctx: Any) -> None:
        service = BrowseDirectoryPickerService(ctx)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: ctx.set_service("directoryPicker", None))


class DirectoryPickerAutoPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-host-directory-picker-auto`:
    Evaluates host facts at boot and mounts the corresponding backend and client surface.
    """

    id = "host-directory-picker-auto"
    name = "@deepseek-ai/dsh-host-directory-picker-auto"
    inject = ["web_server"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.force_kind = (config or {}).get("kind")

    def apply(self, ctx: Any) -> None:
        web_server = ctx.get("web_server")
        bind_host = getattr(web_server, "host", "127.0.0.1") if web_server else "127.0.0.1"

        # Adaptive resolution: local desktop uses native chooser, remote uses browse
        is_local = bind_host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")
        is_desktop = sys.platform in ("win32", "darwin") or (sys.platform.startswith("linux") and "DISPLAY" in os.environ)

        kind = self.force_kind or ("native" if (is_local and is_desktop) else "browse")

        if kind == "native":
            backend_cls = NativeDirectoryPickerPlugin
            client_surface = "@deepseek-ai/dsh-client-ui-directory-picker-native"
        else:
            backend_cls = BrowseDirectoryPickerPlugin
            client_surface = "@deepseek-ai/dsh-client-ui-directory-picker-browse"

        # Mount backend
        ctx.plugin(backend_cls)

        # Register chosen client surface into ClientModuleRegistry
        client_modules = ctx.get("client_modules") or ctx.get("clientModules")
        if client_modules and hasattr(client_modules, "register_dynamic_surface"):
            client_modules.register_dynamic_surface(client_surface)
