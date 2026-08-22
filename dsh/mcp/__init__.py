"""
MCP client bridge package matching reference/packages/mcp/mcp-client
"""
from dsh.mcp.client import McpClientPlugin
from dsh.mcp.connection import McpConnection, RECONNECT_DEFAULTS, resolve_reconnect_policy
from dsh.mcp.tools import extract_text, public_tool_name, sync_tools
from dsh.mcp.transport import StdioMcpTransport, StreamableHttpMcpTransport, create_transport

name = "mcp-client"
inject = ["tools"]

__all__ = [
    "McpClientPlugin",
    "McpConnection",
    "RECONNECT_DEFAULTS",
    "resolve_reconnect_policy",
    "extract_text",
    "public_tool_name",
    "sync_tools",
    "StdioMcpTransport",
    "StreamableHttpMcpTransport",
    "create_transport",
    "name",
    "inject",
]
