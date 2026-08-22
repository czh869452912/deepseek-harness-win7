"""
MCP Client Plugin matching reference/packages/mcp/mcp-client/src/index.ts
"""
import asyncio
from typing import Any, Dict, Optional, Set
from dsh.cordis.plugin import Plugin
from dsh.mcp.connection import McpConnection, resolve_reconnect_policy

_active_server_names: Set[str] = set()


class McpClientPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-mcp-client`: MCP client bridge plugin.
    Connects to external MCP server and registers tools under `mcp__<serverName>__<rawName>`.
    """
    id = "mcp-client"
    name = "@deepseek-ai/dsh-mcp-client"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.config = config or {}
        self.connection: Optional[McpConnection] = None

    def apply(self, ctx: Any) -> None:
        server_name = self.config.get("serverName", "default")
        if server_name in _active_server_names:
            raise ValueError(
                f'mcp-client: serverName "{server_name}" is already in use by another mcp-client instance'
            )
        _active_server_names.add(server_name)

        def _cleanup():
            def _disposer():
                _active_server_names.discard(server_name)
            return _disposer

        if hasattr(ctx, "effect"):
            ctx.effect(_cleanup)

        policy = resolve_reconnect_policy(self.config.get("reconnect"), path=f"mcp-client({server_name}).reconnect")
        self.connection = McpConnection(ctx, self.config, policy)

        if hasattr(ctx, "effect"):
            ctx.effect(lambda: lambda: asyncio.create_task(self.connection.dispose()))

    async def apply_async(self, ctx: Any) -> None:
        self.apply(ctx)
        if self.connection:
            outcome = await self.connection.ready
            if outcome.get("error") and self.config.get("failOnStartupError"):
                raise RuntimeError(
                    f'mcp-client({self.config.get("serverName")}): initial connection or tool synchronization failed'
                ) from outcome["error"]
