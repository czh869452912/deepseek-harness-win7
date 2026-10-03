from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.core.scope import scope_of
from dsh.mcp.connection import McpConnection, resolve_reconnect_policy


_active_server_names = {}


class McpClientPlugin(Plugin):
    id = 'mcp-client'
    name = '@deepseek-ai/dsh-mcp-client'
    inject = ['tools']

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.config = config or {}
        self.connection = None

    async def apply(self, ctx: Any) -> None:
        server_name = self.config.get('serverName', 'default')
        policy = resolve_reconnect_policy(self.config.get('reconnect'),
                                          path='mcp-client(%s): reconnect' % server_name)
        owner = scope_of(ctx)
        if owner is None:
            owner = ctx.root
        owner_id = id(owner)
        def reserve():
            entry = _active_server_names.setdefault(owner_id, (owner, set()))
            names = entry[1]
            if server_name in names:
                raise ValueError('mcp-client: serverName "%s" is already in use by another mcp-client instance — pick a unique serverName in cordis.yml' % server_name)
            names.add(server_name)
            def release():
                names.discard(server_name)
                if not names and _active_server_names.get(owner_id) is entry:
                    _active_server_names.pop(owner_id)
            return release
        ctx.effect(reserve)
        connection = McpConnection(ctx, self.config, policy)
        self.connection = connection
        ctx.effect(lambda: connection.dispose)
        outcome = await connection.ready
        if outcome.get('error') is not None and self.config.get('failOnStartupError'):
            raise RuntimeError('mcp-client(%s): initial connection or tool synchronization failed' % server_name) from outcome['error']

    async def apply_async(self, ctx: Any) -> None:
        await self.apply(ctx)
