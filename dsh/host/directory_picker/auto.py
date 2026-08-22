"""
Auto Directory Picker plugin (`@deepseek-ai/dsh-host-directory-picker-auto`).
Aligned 1:1 with reference `directory-picker-auto/src/index.ts`.
"""

import os
import sys
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.host.directory_picker.browse import BrowseDirectoryPickerPlugin
from dsh.host.directory_picker.native import NativeDirectoryPickerPlugin


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
        web_server = ctx.get("web_server") or ctx.get("webServer")
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
