"""Transient image history projection; durable messages are never rewritten."""
import json
import math


def blocks(content):
    return [{"type": "text", "text": content}] if isinstance(content, str) else content or []


def images(content):
    for block in blocks(content):
        if block.get("type") == "image":
            yield block
        elif block.get("type") == "tool-result":
            yield from images(block.get("content"))


def identity(ref):
    return str(ref["attachmentId"]) if "name" not in ref else "{} ({})".format(json.dumps(ref["name"], ensure_ascii=False), ref["attachmentId"])


def handle(ref, version):
    return "Image {}; request preview {}x{}px. It may be resized or re-encoded; source dimensions, format, and byte size may differ.".format(identity(ref), version["width"], version["height"])


def omitted(ref):
    return "[image omitted to fit request image limits; {}. No local normalized image path is available; ask the user to attach it again if needed.]".format(identity(ref))


def project_text_only(messages):
    if not any(any(images(message.get("content"))) for message in messages):
        return messages
    def project(content):
        result = []
        for block in blocks(content):
            if block.get("type") == "image":
                digest = str(block["attachment"]["attachmentId"])[7:15]
                result.append({"type": "text", "text": "[image omitted because this model accepts text only; attachment sha256:{}]".format(digest)})
            elif block.get("type") == "tool-result":
                result.append(dict(block, content=project(block.get("content"))))
            else:
                result.append(block)
        return result
    return [dict(message, content=project(message.get("content"))) for message in messages]


def offload(messages, max_bytes, max_images, byte_quantum, count_quantum, length, base64=False):
    lengths = [length(block["attachment"]) for message in messages for block in images(message.get("content"))]
    if base64:
        lengths = [math.ceil(size / 3) * 4 for size in lengths]
    excess_count, excess_bytes = max(0, len(lengths) - max_images), max(0, sum(lengths) - max_bytes)
    if not excess_count and not excess_bytes:
        return messages
    remove_count = math.ceil(excess_count / count_quantum) * count_quantum
    remove_bytes = math.ceil(excess_bytes / byte_quantum) * byte_quantum
    count, removed = 0, 0
    for size in lengths:
        target_met = not remove_bytes or (removed >= remove_bytes if byte_quantum == 1 else removed > remove_bytes)
        if count >= remove_count and target_met:
            break
        removed += size
        count += 1
    remaining = [count]
    def project(content):
        result = []
        for block in blocks(content):
            if block.get("type") == "image" and remaining[0]:
                remaining[0] -= 1
                result.append({"type": "text", "text": omitted(block["attachment"])})
            elif block.get("type") == "tool-result":
                result.append(dict(block, content=project(block.get("content"))))
            else:
                result.append(block)
        return result
    return [dict(message, content=project(message.get("content"))) for message in messages]


async def serialize_images(request, versions, resolve_file=None):
    import base64
    from dsh.llm.deepseek_wire import serialize_request
    from dsh.llm.llm_service import LlmError
    wire, pending = [], []
    def flush():
        if pending:
            wire.append({"role": "user", "content": [{"type": "text", "text": "Attached image(s) from tool result:"}] + pending[:]})
            pending.clear()
    async def parts(content, message_number, ordinal):
        result = []
        for block in blocks(content):
            if block.get("type") == "text" and block.get("text"):
                result.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "tool-result":
                result.extend(await parts(block.get("content"), message_number, ordinal))
            elif block.get("type") == "image":
                ordinal[0] += 1
                ref = block["attachment"]
                version = versions.get(ref["attachmentId"])
                if version is None:
                    raise LlmError("DeepSeek request image was not prepared", "INVALID_REQUEST")
                result.append({"type": "text", "text": ("\n" if result else "") + handle(ref, version)})
                if resolve_file is not None:
                    result.append({"type": "file", "file_id": await resolve_file(version, {"message": message_number, "image": ordinal[0]})})
                else:
                    result.append({"type": "image_url", "image_url": {"url": "data:{};base64,{}".format(version["mediaType"], base64.b64encode(version["data"]).decode("ascii"))}})
        return result
    for index, message in enumerate(request["messages"], 1):
        if message["role"] != "user":
            if any(images(message.get("content"))):
                raise LlmError("DeepSeek cannot represent image content in a {} message".format(message["role"]), "UNSUPPORTED_CONTENT")
            flush()
            wire.extend(serialize_request(dict(request, messages=[message], system=None))["messages"])
            continue
        content = blocks(message.get("content"))
        ordinal = [0]
        regular = await parts([block for block in content if block.get("type") != "tool-result"], index, ordinal)
        results = [block for block in content if block.get("type") == "tool-result"]
        if regular or not results:
            flush()
            value = regular if any(part["type"] != "text" for part in regular) else "".join(part["text"] for part in regular)
            wire.append({"role": "user", "content": value})
        for result in results:
            nested = await parts(result.get("content"), index, ordinal)
            text = "".join(part["text"] for part in nested if part["type"] == "text")
            wire.append({"role": "tool", "tool_call_id": result["toolCallId"], "content": text or "(no output)"})
            pending.extend(part for part in nested if part["type"] != "text")
    flush()
    payload = serialize_request(dict(request, messages=[]))
    payload["messages"].extend(wire)
    return payload
