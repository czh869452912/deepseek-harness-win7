"""
Permission Presets plugin (`@deepseek-ai/dsh-permission-presets`).
Manages read-only, workspace-write, and danger-full-access policies.
Aligned 1:1 with official `@deepseek-ai/dsh-permission-presets`.
"""

import os
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class PermissionPresetsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-permission-presets`: Configures permission presets.
    """

    id = "permission"
    name = "@deepseek-ai/dsh-permission-presets"

    def apply(self, ctx: Any) -> None:
        mode = os.environ.get("DSH_PERMISSION_MODE") or self.config.get("mode", "workspace-write")
        approval_svc = ctx.get("approval")
        if approval_svc:
            if mode == "danger-full-access":
                approval_svc.set_policy("never")
            else:
                approval_svc.set_policy("ask")
