"""
Native Directory Picker (`@deepseek-ai/dsh-host-directory-picker-native`).
Aligned 1:1 with reference `directory-picker-native/src/index.ts`.
"""

import asyncio
import os
import subprocess
import sys
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.host.directory_picker.base import DirectoryPickerService


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


class NativeDirectoryPickerPlugin(Plugin):
    id = "host-directory-picker-native"
    name = "@deepseek-ai/dsh-host-directory-picker-native"

    def apply(self, ctx: Any) -> None:
        service = NativeDirectoryPickerService(ctx)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: ctx.set_service("directoryPicker", None))
