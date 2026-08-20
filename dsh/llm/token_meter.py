"""
Token Meter Service mounted at `ctx.token_meter`.
Fixed-density heuristic token pricing shared across compaction, pruning, and agent loop.
"""

import json
import math
from typing import Any, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin

CHARS_PER_TOKEN = 4
BLOCK_OVERHEAD = 4
ROLE_OVERHEAD = 4


def estimate_content(content: Any) -> int:
    """
    Price content blocks recursively under fixed density heuristic.
    """
    if content is None:
        return 0

    if isinstance(content, str):
        return math.ceil(len(content) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD

    if isinstance(content, list):
        tokens = 0
        for block in content:
            if isinstance(block, str):
                tokens += math.ceil(len(block) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD
            elif isinstance(block, dict):
                btype = block.get("type", "text")
                if btype in ("text", "reasoning"):
                    text = block.get("text", "")
                    tokens += math.ceil(len(text) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD
                elif btype == "tool-call":
                    name = block.get("name", "")
                    args = block.get("arguments", "")
                    if not isinstance(args, str):
                        args = json.dumps(args, ensure_ascii=False)
                    tokens += (
                        math.ceil(len(name) / CHARS_PER_TOKEN)
                        + math.ceil(len(args) / CHARS_PER_TOKEN)
                        + BLOCK_OVERHEAD
                    )
                elif btype == "tool-result":
                    res_content = block.get("content", "")
                    tokens += estimate_content(res_content) + BLOCK_OVERHEAD
                else:
                    raw_str = json.dumps(block, ensure_ascii=False)
                    tokens += math.ceil(len(raw_str) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD
        return tokens

    if isinstance(content, dict):
        raw_str = json.dumps(content, ensure_ascii=False)
        return math.ceil(len(raw_str) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD

    return math.ceil(len(str(content)) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD


def estimate_message(message: Dict[str, Any]) -> int:
    """
    Heuristically price one model-visible message.
    """
    if not message:
        return 0

    tokens = 0
    content = message.get("content")
    if content:
        tokens += estimate_content(content)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", tc.get("name", ""))
            args = func.get("arguments", tc.get("arguments", ""))
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            tokens += (
                math.ceil(len(name) / CHARS_PER_TOKEN)
                + math.ceil(len(args) / CHARS_PER_TOKEN)
                + BLOCK_OVERHEAD
            )

    return tokens + ROLE_OVERHEAD


def estimate_system_tokens(header: Optional[Dict[str, Any]]) -> int:
    if not header or not header.get("system"):
        return 0
    system_text = header.get("system", "")
    return math.ceil(len(system_text) / CHARS_PER_TOKEN) + ROLE_OVERHEAD


def estimate_tools_tokens(header: Optional[Dict[str, Any]]) -> int:
    if not header or not header.get("tools"):
        return 0
    tools = header.get("tools", [])
    raw_str = json.dumps(tools, ensure_ascii=False)
    return math.ceil(len(raw_str) / CHARS_PER_TOKEN) + BLOCK_OVERHEAD


def estimate_header(header: Optional[Dict[str, Any]]) -> int:
    return estimate_system_tokens(header) + estimate_tools_tokens(header)


class TokenMeter:
    """
    Token measurement service mounted at `ctx.token_meter`.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx

    def estimate_content(self, content: Any) -> int:
        return estimate_content(content)

    def estimate_message(self, message: Dict[str, Any]) -> int:
        return estimate_message(message)

    def estimate_header(self, header: Optional[Dict[str, Any]]) -> int:
        return estimate_header(header)

    def measure(self, session: Any) -> Dict[str, Any]:
        """
        Price the whole session surface plus request header.
        Returns:
            {
                "total_tokens": int,
                "header_tokens": int,
                "nodes": List[{"seq": int, "tokens": int}]
            }
        """
        nodes = session.surface.nodes if hasattr(session, "surface") else []
        events = session.events if hasattr(session, "events") else []

        header = session.request_header() if hasattr(session, "request_header") else None
        header_tokens = estimate_header(header)

        priced_nodes: List[Dict[str, int]] = []
        surface_tokens = 0

        for seq in nodes:
            if seq < len(events):
                event = events[seq]
                etype = event.get("type")
                edata = event.get("data", {})

                if etype == "user/message":
                    t = estimate_message(edata if "role" in edata else {"role": "user", "content": edata.get("content", "")})
                elif etype == "assistant/message":
                    msg = edata.get("message", edata)
                    t = estimate_message(msg)
                elif etype == "tool/result":
                    t = estimate_message(edata.get("message", {"role": "tool", "content": edata.get("result", "")}))
                else:
                    t = 0

                priced_nodes.append({"seq": seq, "tokens": t})
                surface_tokens += t

        return {
            "total_tokens": header_tokens + surface_tokens,
            "header_tokens": header_tokens,
            "surface_tokens": surface_tokens,
            "nodes": priced_nodes,
        }


class TokenMeterPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-token-meter`: Token measurement and pricing service.
    """

    id = "token-meter"
    name = "@deepseek-ai/dsh-token-meter"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("token_meter"):
            meter = TokenMeter(ctx)
            ctx.set_service("token_meter", meter)
