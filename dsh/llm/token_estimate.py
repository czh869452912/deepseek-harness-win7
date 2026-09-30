"""Fixed-density pricing shared by replay measurement and projection folds."""
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_string_length

CHARS_PER_TOKEN = 4
BLOCK_OVERHEAD = 4
ROLE_OVERHEAD = 4


def _text_tokens(text):
    return (_js_string_length(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_structural_block(block):
    return BLOCK_OVERHEAD + _text_tokens(stringify_json(block))


def estimate_content(content, image_prices=None):
    if content is None:
        return 0
    # Historical Python callers accept text directly; canonical messages use blocks.
    if isinstance(content, str):
        return _text_tokens(content) + BLOCK_OVERHEAD
    if isinstance(content, dict):
        return estimate_structural_block(content)
    tokens = 0
    for block in content:
        if isinstance(block, str):
            tokens += _text_tokens(block) + BLOCK_OVERHEAD
            continue
        kind = block.get("type")
        if kind in ("text", "reasoning"):
            tokens += _text_tokens(block["text"]) + BLOCK_OVERHEAD
        elif kind == "tool-call":
            args = block["arguments"]
            if not isinstance(args, str):
                args = stringify_json(args)
            tokens += _text_tokens(block["name"]) + _text_tokens(args) + BLOCK_OVERHEAD
        elif kind == "tool-result":
            tokens += estimate_content(block["content"], image_prices) + BLOCK_OVERHEAD
        elif kind == "image" and image_prices is not None:
            price = next(image_prices)
            tokens += price["visualTokens"] + estimate_content([dict(type="text", text=price["text"])])
        else:
            tokens += estimate_structural_block(block)
    return tokens


def estimate_message(message, image_prices=None):
    if not message:
        return 0
    tokens = estimate_content(message.get("content", []), image_prices)
    for call in message.get("tool_calls") or []:
        function = call.get("function", call)
        tokens += estimate_content([dict(type="tool-call", name=function.get("name", ""),
                                        arguments=function.get("arguments", ""))])
    return tokens + ROLE_OVERHEAD


def estimate_system_tokens(header):
    if header is None or "system" not in header:
        return 0
    return _text_tokens(header["system"]) + ROLE_OVERHEAD


def estimate_tools_tokens(header):
    if header is None or not header.get("tools"):
        return 0
    return _text_tokens(stringify_json(header["tools"])) + BLOCK_OVERHEAD


def estimate_header(header):
    return estimate_system_tokens(header) + estimate_tools_tokens(header)
