"""
Agent-plane presentation selector.
1:1 aligned with official `@deepseek-ai/dsh-agent-tool-presentation`.
"""

from typing import Any, Dict, Optional
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin


class AgentToolPresentationPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-tool-presentation`: Configures tool presentation mode (native, ptc, both).
    """

    id = "tool-presentation"
    name = "@deepseek-ai/dsh-agent-tool-presentation"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def apply(self, ctx: Context) -> None:
        mode = self.config.get("mode", "native")
        tools_svc = ctx.get("tools")
        if not tools_svc:
            return

        if mode == "native":
            if hasattr(tools_svc, "present_as"):
                tools_svc.present_as("native")
            elif hasattr(tools_svc, "presentAs"):
                tools_svc.presentAs("native")
            return

        # ptc / both mode
        if hasattr(ctx, "inject"):
            def _on_code_runtime(runtime_ctx: Context):
                ts = runtime_ctx.get("tools")
                if ts and hasattr(ts, "present_as"):
                    ts.present_as(mode)
                elif ts and hasattr(ts, "presentAs"):
                    ts.presentAs(mode)
            ctx.inject(["codeRuntime"], _on_code_runtime)
        else:
            if hasattr(tools_svc, "present_as"):
                tools_svc.present_as(mode)
            elif hasattr(tools_svc, "presentAs"):
                tools_svc.presentAs(mode)
