"""
MCP tool bridge matching reference/packages/mcp/mcp-client/src/tools.ts
"""
import hashlib
import inspect
import re
from typing import Any, Callable, Dict, List, Optional, Union


def public_tool_name(server_name: str, raw_name: str) -> str:
    """
    Derive model-facing public tool name for an MCP tool.
    Formula: mcp__<serverName>__<rawName>, max length 64, chars [A-Za-z0-9_-].
    If truncated or characters changed, appends _<sha256[:12]>.
    """
    joined = f"mcp__{server_name}__{raw_name}"
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", joined)
    if normalized == joined and len(normalized) <= 64:
        return normalized
    raw_hash = hashlib.sha256(f"{server_name}\0{raw_name}".encode("utf-8")).hexdigest()[:12]
    prefix = normalized[:64 - 12 - 1]
    return f"{prefix}_{raw_hash}"


def extract_text(mcp_content: List[Dict[str, Any]], tool_name: str) -> str:
    """
    Extract text from MCP content blocks.
    """
    lines: List[str] = []
    for block in mcp_content:
        if not isinstance(block, dict):
            lines.append("[unsupported MCP content block: expected an object]")
            continue
        b_type = block.get("type", "")
        if b_type == "text":
            if "text" in block and block["text"] is not None:
                lines.append(str(block["text"]))
        elif b_type == "resource_link":
            name = block.get("name")
            uri = block.get("uri")
            if name is None or uri is None:
                lines.append("[resource link unavailable: missing name or URI]")
            else:
                lines.append(f"Resource link: {name} ({uri})")
        elif b_type == "image":
            mime = block.get("mimeType", "unknown media type")
            lines.append(f"[image unavailable: {mime}; raw image data remains available]")
        elif b_type == "audio":
            mime = block.get("mimeType", "unknown media type")
            lines.append(f"[audio result unsupported: {mime}]")
        elif b_type == "resource":
            lines.append("[embedded resource unsupported]")
        else:
            lines.append(f"[unsupported MCP content type: {b_type}]")

    text = "\n".join(lines)
    return text if text else f"({tool_name} returned no model-visible content)"


async def sync_tools(
    client: Any,
    ctx: Any,
    opts: Dict[str, Any],
    previous: Dict[str, Callable[[], None]],
) -> Dict[str, Callable[[], None]]:
    """
    Synchronize MCP server's tools with harness ToolsService context.
    """
    server_name = opts.get("serverName", "default")
    if hasattr(client, "list_tools"):
        raw_tools = client.list_tools()
        if inspect.isawaitable(raw_tools):
            raw_tools = await raw_tools
    else:
        raw_tools = []

    new_definitions: Dict[str, Dict[str, Any]] = {}
    for tool in raw_tools:
        raw_name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", "")
        desc = tool.get("description", "") if isinstance(tool, dict) else getattr(tool, "description", "")
        params = tool.get("inputSchema", {}) if isinstance(tool, dict) else getattr(tool, "inputSchema", {})
        pub_name = public_tool_name(server_name, raw_name)
        if pub_name in new_definitions:
            raise ValueError(f"mcp-client({server_name}): duplicate tool name '{raw_name}'")

        def make_executor(r_name: str):
            async def _executor(*args_pos: Any, **kwargs: Any) -> Dict[str, Any]:
                call_args = args_pos[0] if args_pos and isinstance(args_pos[0], dict) else kwargs
                if hasattr(client, "call_tool"):
                    res = client.call_tool(r_name, call_args)
                    if inspect.isawaitable(res):
                        res = await res
                else:
                    res = {}
                if isinstance(res, dict) and res.get("isError"):
                    err_text = extract_text(res.get("content", []), r_name)
                    raise RuntimeError(err_text)
                content = res.get("content", []) if isinstance(res, dict) else []
                text_out = extract_text(content, r_name)
                return {"content": [{"type": "text", "text": text_out}], "raw": res}
            return _executor

        new_definitions[pub_name] = {
            "name": pub_name,
            "description": desc,
            "parameters": params,
            "execute": make_executor(raw_name),
        }

    for disp in previous.values():
        try:
            disp()
        except Exception:
            pass

    disposers: Dict[str, Callable[[], None]] = {}
    tools_svc = ctx.get("tools") if hasattr(ctx, "get") else getattr(ctx, "tools", None)
    if tools_svc:
        for pub_name, spec in new_definitions.items():
            disp = tools_svc.register(spec)
            disposers[pub_name] = disp
    return disposers
