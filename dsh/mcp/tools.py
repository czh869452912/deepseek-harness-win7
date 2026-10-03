"""
MCP tool bridge matching reference/packages/mcp/mcp-client/src/tools.ts
"""
import hashlib
import inspect
import json
import math
import re
import weakref
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.mcp.content import extract_text, prepare_image_projection

try:
    from dsh.core.tools import _assert_supported_schema
except ImportError:  # pragma: no cover - defensive import for isolated use
    _assert_supported_schema = None


def public_tool_name(server_name: str, raw_name: str) -> str:
    """
    Derive model-facing public tool name for an MCP tool.
    Formula: mcp__<serverName>__<rawName>, max length 64, chars [A-Za-z0-9_-].
    If truncated or characters changed, appends _<sha256[:12]>.
    """
    joined = f"mcp__{server_name}__{raw_name}"
    encoded = joined.encode('utf-16-le', errors='surrogatepass')
    units = ''.join(chr(int.from_bytes(encoded[offset:offset + 2], 'little')) for offset in range(0, len(encoded), 2))
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", units)
    if normalized == joined and len(normalized) <= 64:
        return normalized
    identity = (server_name + '\0' + raw_name).encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace')
    raw_hash = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]
    prefix = normalized[:64 - 12 - 1]
    return f"{prefix}_{raw_hash}"
def _same_json(left, right):
    if isinstance(left, dict) or isinstance(right, dict):
        return (isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys()
            and all(_same_json(value, right[key]) for key, value in left.items()))
    if isinstance(left, list) or isinstance(right, list):
        return (isinstance(left, list) and isinstance(right, list) and len(left) == len(right)
            and all(_same_json(first, second) for first, second in zip(left, right)))
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right and (left != 0 or math.copysign(1, left) == math.copysign(1, right))
    return type(left) is type(right) and left == right


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
    registration_failure = opts.get("registrationFailure", "contain")
    if registration_failure not in ("contain", "throw"):
        raise ValueError("registrationFailure must be 'contain' or 'throw'")

    # Drain the complete tools/list cursor chain before touching the registry.
    raw_tools: List[Any] = []
    cursor = None
    while True:
        if hasattr(client, "request"):
            request = {"method": "tools/list"}
            if cursor is not None:
                request["params"] = {"cursor": cursor}
            page = client.request(request)
        elif hasattr(client, "list_tools"):
            try:
                page = client.list_tools(cursor)
            except TypeError:
                page = client.list_tools()
        else:
            page = []
        if inspect.isawaitable(page):
            page = await page
        if isinstance(page, dict):
            raw_tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor") or page.get("next_cursor")
        else:
            raw_tools.extend(page or [])
            cursor = None
        if not cursor:
            break

    new_definitions: Dict[str, Dict[str, Any]] = {}
    for tool in raw_tools:
        raw_name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", "")
        desc = tool.get("description", "") if isinstance(tool, dict) else getattr(tool, "description", "")
        params = tool.get("inputSchema", {}) if isinstance(tool, dict) else getattr(tool, "inputSchema", {})
        output_schema_candidate = tool.get("outputSchema") if isinstance(tool, dict) else getattr(tool, "outputSchema", None)
        pub_name = public_tool_name(server_name, raw_name)
        if pub_name in new_definitions:
            raise ValueError('mcp-client(%s): server listed tool "%s" more than once — invalid tool list' % (server_name, raw_name))

        execution = tool.get("execution", {}) if isinstance(tool, dict) else getattr(tool, "execution", {})
        task_required = bool(
            (execution.get("taskSupport") if isinstance(execution, dict) else getattr(execution, "taskSupport", None)) == "required"
        )

        def make_executor(r_name: str, requires_task: bool):
            projections = weakref.WeakKeyDictionary()
            async def _executor(args: Any, exec: Any) -> Dict[str, Any]:
                if requires_task:
                    raise RuntimeError('Tool "%s" requires task-based execution, which this bridge does not support' % r_name)
                call_args = args if isinstance(args, (dict, list)) else {}
                if hasattr(client, "request"):
                    request = {"method": "tools/call", "params": {"name": r_name, "arguments": call_args}}
                    try:
                        res = client.request(
                            request,
                            signal=getattr(exec, "signal", None),
                            timeout=opts.get("toolCallTimeoutMs", 60000),
                        )
                    except TypeError:
                        res = client.request(request)
                elif hasattr(client, "call_tool"):
                    res = client.call_tool(r_name, call_args)
                else:
                    res = {}
                if inspect.isawaitable(res):
                    res = await res
                if not isinstance(res, dict):
                    res = {}
                if not isinstance(res.get("content"), list):
                    text_out = json.dumps(res.get("toolResult"), ensure_ascii=False, separators=(',', ':')) if "toolResult" in res else "(no output)"
                    if res.get("isError") is True:
                        raise RuntimeError(text_out)
                    return {"content": [{"type": "text", "text": text_out}], **({"structuredContent": res["structuredContent"]} if "structuredContent" in res else {})}
                content = res.get("content", [])
                if res.get("isError") is True:
                    raise RuntimeError(extract_text(content, r_name))
                result = {"content": content}
                if "structuredContent" in res:
                    result["structuredContent"] = res["structuredContent"]
                if any(isinstance(block, dict) and block.get('type') == 'image' for block in content):
                    projected = await prepare_image_projection(ctx, exec, content, r_name)
                    projections[exec] = {'value': result, 'fallback': [{'type': 'text', 'text': extract_text(content, r_name)}],
                        'content': projected}
                return result
            def finalize(execution, result):
                projection = projections.pop(execution, None)
                if projection is None:
                    return None
                value = result.get('value') if isinstance(result, dict) else result.value
                content = result.get('content') if isinstance(result, dict) else result.content
                is_error = result.get('isError') if isinstance(result, dict) else result.isError
                if is_error or not _same_json(value, projection['value']) or not _same_json(content, projection['fallback']):
                    return None
                return projection['content']
            return _executor, finalize

        def render_output(_args: Any, value: Dict[str, Any], wire_name: str = raw_name) -> List[Dict[str, str]]:
            return [{"type": "text", "text": extract_text(value.get("content", []), wire_name)}]

        supported_output = output_schema_candidate
        if supported_output is not None and _assert_supported_schema is not None:
            try:
                _assert_supported_schema(supported_output, "outputSchema")
            except Exception:
                supported_output = None
        output_schema = {
            "type": "object",
            "properties": {"content": {"type": "array", "items": {}}, "structuredContent": supported_output or {}},
            "required": ["content"] if supported_output is None else ["content", "structuredContent"],
            "additionalProperties": False,
        }

        execute, finalize = make_executor(raw_name, task_required)
        new_definitions[pub_name] = {
            "name": pub_name,
            "description": desc,
            "parameters": params,
            "output": {"schema": output_schema, "render": render_output},
            "execute": execute,
            "finalizeContent": finalize,
        }

    is_current = opts.get("isCurrent")
    if is_current is not None and not is_current():
        return previous

    for disp in previous.values():
        try:
            disp()
        except Exception:
            pass

    disposers: Dict[str, Callable[[], None]] = {}
    tools_svc = ctx.get("tools") if hasattr(ctx, "get") else getattr(ctx, "tools", None)
    if tools_svc:
        try:
            for pub_name, spec in new_definitions.items():
                disp = tools_svc.register(spec)
                disposers[pub_name] = disp
        except Exception:
            for disp in disposers.values():
                try:
                    disp()
                except Exception:
                    pass
            if registration_failure == "throw":
                raise
            return {}
    return disposers
