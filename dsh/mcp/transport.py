"""
MCP transport factory matching reference/packages/mcp/mcp-client/src/transport.ts
"""
from typing import Any, Dict, List, Optional
from dsh.mcp.stdio_client import StdioMcpClient
from dsh.mcp.http_client import StreamableHttpMcpClient


class StdioMcpTransport(StdioMcpClient):
    """
    Child-process stdio MCP transport.
    """

    pass


class StreamableHttpMcpTransport(StreamableHttpMcpClient):
    """
    Streamable HTTP (SSE) MCP transport.
    """

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
