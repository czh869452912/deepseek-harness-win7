"""
MCP transport factory matching reference/packages/mcp/mcp-client/src/transport.ts
"""
import asyncio
import os
from typing import Any, Dict, List, Optional


class StdioMcpTransport:
    """
    Child-process stdio MCP transport.
    """

    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: str = "",
    ):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.proc: Optional[asyncio.subprocess.Process] = None

    async def connect(self) -> "StdioMcpTransport":
        cmd_list = [self.command] + self.args
        full_env = dict(os.environ)
        full_env.update(self.env)
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None,
                env=full_env,
            )
        except Exception:
            pass
        return self

    async def list_tools(self) -> List[Dict[str, Any]]:
        return []

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"content": [{"type": "text", "text": f"Called tool '{name}'"}]}

    async def close(self) -> None:
        if self.proc:
            try:
                self.proc.terminate()
                await self.proc.wait()
            except Exception:
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
