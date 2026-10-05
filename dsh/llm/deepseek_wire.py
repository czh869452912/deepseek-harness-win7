"""DeepSeek text wire boundary, following the pinned serialize/SSE/translate contract."""
import codecs
import json


def _error(message, code):
    from dsh.llm.llm_service import LlmError
    return LlmError(message, code)


def _blocks(content):
    return [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])


def _text(content):
    blocks = _blocks(content)
    for block in blocks:
        if block.get("type") == "image":
            raise _error("Image content requires a prepared attachment representation", "UNSUPPORTED_CONTENT")
        if block.get("type") == "tool-result":
            _text(block.get("content"))
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def serialize_request(options, defaults=None):
    defaults = defaults or {}
    wire = []
    if options.get("system") is not None:
        wire.append({"role": "system", "content": options["system"]})
    for message in options["messages"]:
        content = _blocks(message.get("content"))
        text = _text(content)
        role = message["role"]
        if role in ("system", "assistant"):
            row = {"role": role, "content": text}
            if role == "assistant":
                reasoning = "".join(b.get("text", "") for b in content if b.get("type") == "reasoning")
                calls = [{"id": b["id"], "type": "function", "function": {
                    "name": b["name"], "arguments": b["arguments"]}}
                    for b in content if b.get("type") == "tool-call"]
                if reasoning:
                    row["reasoning_content"] = reasoning
                if calls:
                    row["tool_calls"] = calls
            wire.append(row)
        else:
            results = [b for b in content if b.get("type") == "tool-result"]
            if text or not results:
                wire.append({"role": "user", "content": text})
            for result in results:
                wire.append({"role": "tool", "tool_call_id": result["toolCallId"],
                             "content": _text(result.get("content")) or "(no output)"})
    payload = {"model": options["model"], "messages": wire, "stream": True,
               "stream_options": {"include_usage": True}}
    if options.get("tools"):
        payload["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t["parameters"]}} for t in options["tools"]]
    for key, target in (("temperature", "temperature"), ("maxTokens", "max_tokens"), ("stop", "stop")):
        if options.get(key) is not None:
            payload[target] = options[key]
    effort = options.get("reasoningEffort", defaults.get("reasoningEffort"))
    thinking = defaults.get("thinking")
    if options.get("purpose") == "session-title":
        thinking, effort = "disabled", None
    elif effort is not None:
        if effort not in ("off", "low", "high", "max") or (thinking == "disabled" and effort != "off"):
            raise _error("DeepSeek does not support reasoning effort {!r}".format(effort), "UNSUPPORTED_REASONING_EFFORT")
        thinking = "disabled" if effort == "off" else "enabled"
    if thinking is not None:
        payload["thinking"] = {"type": thinking}
    if effort in ("low", "high", "max"):
        payload["reasoning_effort"] = effort
    return payload


def parse_sse(chunks, require_done=True):
    """Decode UTF-8 incrementally and dispatch only complete SSE events."""
    decoder = codecs.getincrementaldecoder("utf-8-sig")("replace")
    line, data, after_cr = "", [], False
    for chunk in chunks:
        for char in decoder.decode(chunk):
            if after_cr:
                after_cr = False
                if char == "\n":
                    continue
            if char not in "\r\n":
                line += char
                continue
            after_cr = char == "\r"
            if line == "" and data:
                value = "\n".join(data)
                data = []
                yield value
                if value == "[DONE]":
                    return
            elif line == "data" or line.startswith("data:"):
                value = line[5:]
                data.append(value[1:] if value.startswith(" ") else value)
            line = ""
    if require_done:
        raise _error("SSE stream ended without [DONE]", "STREAM_CLOSED")


def map_usage(usage):
    prompt, completion = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    cache = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", usage.get("prompt_cache_hit_tokens"))
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    result = {"inputTokens": prompt - (cache or 0), "outputTokens": completion}
    total = prompt + completion
    if all(type(n) is int and 0 <= n <= 9007199254740991 for n in (prompt, completion, total)) and usage.get("total_tokens", total) == total:
        result["totalTokens"] = total
    if cache is not None:
        result["cacheReadTokens"] = cache
    if reasoning is not None:
        result["reasoningTokens"] = reasoning
    return result


def translate(payloads):
    blocks, indexes, finish, usage = [], {}, {"kind": "stop"}, None
    for payload in payloads:
        if payload == "[DONE]":
            for index, block in enumerate(blocks):
                yield {"type": "block-end", "index": index, "block": block}
            if usage is not None:
                yield {"type": "usage", "usage": usage}
            if not blocks and finish["kind"] == "stop":
                finish = {"kind": "error", "failure": {"message": "model returned a completed response with no content", "code": "EMPTY_RESPONSE"}}
            yield {"type": "finish", "reason": finish}
            return
        try:
            chunk = json.loads(payload)
            if not isinstance(chunk, dict):
                raise ValueError("expected an object")
        except (ValueError, TypeError) as error:
            preview = payload.encode("utf-16-le", "surrogatepass")[:240].decode("utf-16-le", "surrogatepass")
            raise _error("malformed SSE payload: {}".format(preview), "MALFORMED_RESPONSE") from error
        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            for field, kind in (("reasoning_content", "reasoning"), ("content", "text")):
                value = delta.get(field)
                if not isinstance(value, str) or not value:
                    continue
                if kind not in indexes:
                    indexes[kind] = len(blocks)
                    blocks.append({"type": kind, "text": ""})
                    yield {"type": "block-start", "index": indexes[kind], "blockType": kind}
                index = indexes[kind]
                blocks[index]["text"] += value
                yield {"type": kind + "-delta", "index": index, "text": value}
            for call in delta.get("tool_calls", []):
                key = ("tool-call", call.get("index"))
                if key not in indexes:
                    indexes[key] = len(blocks)
                    blocks.append({"type": "tool-call", "id": "", "name": "", "arguments": ""})
                    yield {"type": "block-start", "index": indexes[key], "blockType": "tool-call"}
                index = indexes[key]
                block, function = blocks[index], call.get("function") or {}
                if "id" in call:
                    block["id"] = call["id"]
                if "name" in function:
                    block["name"] = function["name"]
                fragment = function.get("arguments", "")
                block["arguments"] += fragment
                yield {"type": "tool-call-delta", "index": index, "id": block["id"],
                       "name": block["name"], "argumentsDelta": fragment}
            reason = choice.get("finish_reason")
            if isinstance(reason, str):
                kind = {"stop": "stop", "tool_calls": "tool-calls", "length": "max-tokens"}.get(reason)
                finish = {"kind": kind} if kind else {"kind": "error", "failure": {
                    "message": "model stopped: " + reason, "code": reason.upper()}}
        if chunk.get("usage"):
            usage = map_usage(chunk["usage"])
    raise _error("SSE payload stream ended without [DONE]", "STREAM_CLOSED")
