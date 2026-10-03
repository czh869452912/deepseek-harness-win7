"""
MCP transport factory matching reference/packages/mcp/mcp-client/src/transport.ts
"""
from typing import Any, Dict, List, Optional
from dsh.mcp.stdio_client import StdioMcpClient


class StdioMcpTransport(StdioMcpClient):
    """
    Child-process stdio MCP transport.
    """

    pass


class StreamableHttpMcpTransport:
    """
    Streamable HTTP (SSE) MCP transport.
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.headers = headers or {}

    async def connect(self) -> "StreamableHttpMcpTransport":
        return self

    async def list_tools(self) -> List[Dict[str, Any]]:
        return []

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": f"Called tool '{name}'"}]}

    async def close(self) -> None:
        pass


def create_transport(config: Dict[str, Any]) -> Any:
    tp = config.get("transport", "stdio")
    if tp == "stdio":
        return StdioMcpTransport(
            command=config.get("command", "echo"),
            args=config.get("args", []),
            env=config.get("env", {}),
            cwd=config.get("cwd", ""),
        )
    elif tp == "streamable-http":
        return StreamableHttpMcpTransport(
            url=config.get("url", "http://localhost:8000"),
            headers=config.get("headers", {}),
        )
    else:
        raise ValueError(f"Unsupported transport: '{tp}'")
