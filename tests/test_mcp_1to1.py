"""
Unit tests for MCP plugin (dsh/mcp) matching TypeScript reference
"""
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.mcp import (
    McpClientPlugin,
    McpConnection,
    StdioMcpTransport,
    StreamableHttpMcpTransport,
    extract_text,
    public_tool_name,
    resolve_reconnect_policy,
    sync_tools,
)


def test_public_tool_name_clean():
    # Clean case: mcp__<serverName>__<rawName>
    name = public_tool_name("fs", "read_file")
    assert name == "mcp__fs__read_file"


def test_public_tool_name_truncation_and_hashing():
    # Long name or invalid chars -> truncated to 64 chars with 12-char SHA-256 hash appended
    raw = "a_very_long_tool_name_that_exceeds_the_maximum_allowed_length_for_deepseek_function_names"
    name = public_tool_name("server1", raw)
    assert len(name) <= 64
    assert "_" in name


def test_extract_text_content_blocks():
    content = [
        {"type": "text", "text": "Hello world"},
        {"type": "resource_link", "name": "doc", "uri": "file:///doc.txt"},
        {"type": "image", "mimeType": "image/png"},
    ]
    text = extract_text(content, "test_tool")
    assert "Hello world" in text
    assert "Resource link: doc (file:///doc.txt)" in text
    assert "[image unavailable" in text


def test_resolve_reconnect_policy():
    policy = resolve_reconnect_policy({"initialDelayMs": 1000, "maxAttempts": 5})
    assert policy["initialDelayMs"] == 1000
    assert policy["maxAttempts"] == 5
    assert policy["enabled"] is True

    with pytest.raises(ValueError):
        resolve_reconnect_policy({"invalid_option": 123})

    with pytest.raises(ValueError):
        resolve_reconnect_policy({"initialDelayMs": 5000, "maxDelayMs": 1000})


@pytest.mark.asyncio
async def test_mcp_sync_tools_and_execution():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    class MockMcpClient:
        async def list_tools(self):
            return [
                {"name": "fetch", "description": "Fetch URL", "inputSchema": {"type": "object"}},
            ]

        async def call_tool(self, name, args):
            return {"content": [{"type": "text", "text": f"Result for {name}"}], "isError": False}

    client = MockMcpClient()
    opts = {"serverName": "web", "toolCallTimeoutMs": 5000}
    disposers = await sync_tools(client, ctx, opts, {})
    assert "mcp__web__fetch" in disposers

    assert tools.has_tool("mcp__web__fetch")
    res = await tools.execute_tool("mcp__web__fetch", {})
    assert "Result for fetch" in res

    # Unregister
    for d in disposers.values():
        d()
    assert not tools.has_tool("mcp__web__fetch")


@pytest.mark.asyncio
async def test_mcp_plugin_apply():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    plugin = McpClientPlugin({"serverName": "test_server", "transport": "streamable-http", "url": "http://localhost:8000"})
    plugin.apply(ctx)
    assert plugin.connection is not None
    await plugin.connection.dispose()


@pytest.mark.asyncio
async def test_mcp_sync_tools_drains_cursor_pages_and_preserves_structured_content():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    class Client:
        async def request(self, request):
            cursor = request.get("params", {}).get("cursor")
            if request["method"] == "tools/list":
                if cursor is None:
                    return {"tools": [{"name": "one", "inputSchema": {"type": "object"}}], "nextCursor": "p2"}
                return {"tools": [{"name": "two", "inputSchema": {"type": "object"}, "outputSchema": {"type": "string"}}]}
            return {"content": [{"type": "text", "text": "ok"}], "structuredContent": "value"}

    live = await sync_tools(Client(), ctx, {"serverName": "pager"}, {})
    assert set(live) == {"mcp__pager__one", "mcp__pager__two"}
    second = tools.get_tool("mcp__pager__two")
    assert second is not None and second.output["schema"]["required"] == ["content", "structuredContent"]
    result = await second.execute({}, None)
    assert result["structuredContent"] == "value"


@pytest.mark.asyncio
async def test_mcp_registration_failure_contain_and_throw_roll_back_generation():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    tools.register_legacy({"name": "mcp__conflict__one", "parameters": {}, "handler": lambda **_: "foreign"})

    class Client:
        async def list_tools(self):
            return [{"name": "one", "inputSchema": {"type": "object"}}, {"name": "two", "inputSchema": {"type": "object"}}]

    contained = await sync_tools(Client(), ctx, {"serverName": "conflict", "registrationFailure": "contain"}, {})
    assert contained == {}
    assert not tools.has_tool("mcp__conflict__two")
    with pytest.raises(ValueError):
        await sync_tools(Client(), ctx, {"serverName": "conflict", "registrationFailure": "throw"}, {})
