"""
MCP connection supervisor matching reference/packages/mcp/mcp-client/src/connection.ts
"""
import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional
from dsh.mcp.tools import sync_tools
from dsh.mcp.transport import create_transport

RECONNECT_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "initialDelayMs": 500,
    "maxDelayMs": 30000,
    "maxAttempts": 10,
}


def resolve_reconnect_policy(
    config: Optional[Dict[str, Any]] = None,
    path: str = "mcp_client",
) -> Dict[str, Any]:
    """
    Resolve and validate reconnect policy options.
    """
    cfg = config or {}
    for k in cfg:
        if k not in RECONNECT_DEFAULTS:
            raise ValueError(f"{path}.{k} is not a reconnect option")
    enabled = cfg.get("enabled", RECONNECT_DEFAULTS["enabled"])
    initial_delay_ms = cfg.get("initialDelayMs", RECONNECT_DEFAULTS["initialDelayMs"])
    max_delay_ms = cfg.get("maxDelayMs", RECONNECT_DEFAULTS["maxDelayMs"])
    max_attempts = cfg.get("maxAttempts", RECONNECT_DEFAULTS["maxAttempts"])

    if not isinstance(initial_delay_ms, (int, float)) or initial_delay_ms <= 0 or initial_delay_ms > 2147483647:
        raise ValueError(f"{path}.initialDelayMs must be a positive finite number no greater than 2147483647")
    if not isinstance(max_delay_ms, (int, float)) or max_delay_ms <= 0 or max_delay_ms > 2147483647:
        raise ValueError(f"{path}.maxDelayMs must be a positive finite number no greater than 2147483647")
    if initial_delay_ms > max_delay_ms:
        raise ValueError(f"{path}.initialDelayMs must be less than or equal to maxDelayMs")
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError(f"{path}.maxAttempts must be a positive integer")

    return {
        "enabled": enabled,
        "initialDelayMs": initial_delay_ms,
        "maxDelayMs": max_delay_ms,
        "maxAttempts": max_attempts,
    }


class McpConnection:
    """
    Supervises connection to an MCP server, maintaining tools and reconnect attempts.
    """

    def __init__(self, ctx: Any, config: Dict[str, Any], policy: Dict[str, Any]):
        self.ctx = ctx
        self.config = config
        self.policy = policy
        self.disposed: bool = False
        self.disposers: Dict[str, Callable[[], None]] = {}
        self.client: Optional[Any] = None

        loop = asyncio.get_event_loop()
        self.ready: asyncio.Future = loop.create_future()
        self._start_task = loop.create_task(self._connect_and_sync())

    async def _connect_and_sync(self) -> None:
        try:
            transport = create_transport(self.config)
            if hasattr(transport, "connect"):
                res = transport.connect()
                self.client = await res if inspect.isawaitable(res) else res
            else:
                self.client = transport

            opts = {
                "serverName": self.config.get("serverName", "default"),
                "toolCallTimeoutMs": self.config.get("toolCallTimeoutMs", 60000),
            }
            self.disposers = await sync_tools(self.client, self.ctx, opts, self.disposers)
            if not self.ready.done():
                self.ready.set_result({"error": None})
        except Exception as e:
            if not self.ready.done():
                self.ready.set_result({"error": e})

    async def dispose(self) -> None:
        self.disposed = True
        for disp in list(self.disposers.values()):
            try:
                disp()
            except Exception:
                pass
        self.disposers.clear()
        if self.client and hasattr(self.client, "close"):
            res = self.client.close()
            if inspect.isawaitable(res):
                await res
