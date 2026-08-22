"""
In-Process Fetch Carrier Client (`@deepseek-ai/dsh-host-apiproxy/fetch/client`).
In-process client implementation for testing and direct invocation.
Aligned 1:1 with reference `fetch/client.ts`.
"""

from typing import Any, Dict


class InProcessApiClient:
    """In-process API client adapter."""

    def __init__(self, api_proxy: Any):
        self.api_proxy = api_proxy

    async def request(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke RPC method directly in-process."""
        return await self.api_proxy.dispatch_rpc(method, payload)
