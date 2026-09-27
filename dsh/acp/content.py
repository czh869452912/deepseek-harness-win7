"""
ACP wire content admission and projection matching reference/packages/acp/acp/src/content.ts
"""
import base64
import binascii
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

IMAGE_MEDIA_TYPES: Tuple[str, ...] = ("image/png", "image/jpeg", "image/webp", "image/gif")
_CANONICAL_BASE64 = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")


class AcpContentError(Exception):
    """
    Error with stable ACP request-failure category ('invalid' or 'internal').
    """

    def __init__(self, message: str, kind: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.kind = kind


def supports_acp_image_prompts(ctx: Any, provider: Optional[str] = None, model: Optional[str] = None) -> bool:
    """
    Determine whether initialization may advertise inline image prompts.
    """
    if not ctx:
        return False
    attachments = ctx.get("attachments") if hasattr(ctx, "get") else None
    llm = ctx.get("llm") if hasattr(ctx, "get") else None
    if not attachments or not llm:
        return False
    return True


def admit_acp_prompt(
    ctx: Any,
    agent: Any,
    prompt: List[Dict[str, Any]],
    image_enabled: bool = False,
) -> List[Dict[str, Any]]:
    """
    Admit ACP prompt blocks into ordered durable core content.
    """
    content: List[Dict[str, Any]] = []
    text_accum: List[str] = []

    def flush_text() -> None:
        if text_accum:
            content.append({"type": "text", "text": "".join(text_accum)})
            text_accum.clear()

    for block in prompt:
        if not isinstance(block, dict):
            continue
        b_type = block.get("type", "text")
        if b_type == "text":
            text_accum.append(block.get("text", ""))
        elif b_type == "resource_link":
            name = block.get("name", "")
            uri = block.get("uri", "")
            text_accum.append("\n[resource_link name=%s uri=%s]\n" % (json.dumps(name, ensure_ascii=False), json.dumps(uri, ensure_ascii=False)))
        elif b_type == "image":
            if not image_enabled:
                raise AcpContentError("inline image prompts were not advertised by this connection", "invalid")
            mime_type = block.get("mimeType", "")
            if mime_type not in IMAGE_MEDIA_TYPES:
                raise AcpContentError("image mimeType must be image/png, image/jpeg, image/webp, or image/gif", "invalid")
            data_b64 = block.get("data", "")
            if not isinstance(data_b64, str) or not _CANONICAL_BASE64.match(data_b64):
                raise AcpContentError("image data must be canonical base64", "invalid")
            try:
                img_bytes = base64.b64decode(data_b64, validate=True)
            except (TypeError, ValueError, binascii.Error) as e:
                raise AcpContentError("image data must be canonical base64", "invalid") from e
            if base64.b64encode(img_bytes).decode("ascii") != data_b64:
                raise AcpContentError("image data must be canonical base64", "invalid")

            flush_text()
            attachments = ctx.get("attachments") if hasattr(ctx, "get") else None
            if attachments and hasattr(attachments, "save_images"):
                refs = attachments.save_images([{"data": img_bytes, "mediaType": mime_type}])
                content.append({"type": "image", "attachment": refs[0] if refs else {}})
            else:
                content.append({"type": "text", "text": f"[image prompt admitted: {len(img_bytes)} bytes]"})
        elif b_type == "audio":
            raise AcpContentError("audio prompt content is not supported", "invalid")
        elif b_type == "resource":
            raise AcpContentError("embedded resource prompt content is not supported", "invalid")
        else:
            raise AcpContentError("unsupported ACP prompt content", "invalid")

    flush_text()
    if not any(item.get("type") == "image" or (item.get("type") == "text" and item.get("text", "").strip()) for item in content):
        raise AcpContentError("empty prompt", "invalid")
    return content


def assistant_block_to_acp(ctx: Any, block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Translate one committed assistant block to ACP wire content.
    """
    b_type = block.get("type")
    if b_type == "text":
        txt = block.get("text", "")
        return {"type": "text", "text": txt} if txt else None
    elif b_type == "image":
        attachments = ctx.get("attachments") if hasattr(ctx, "get") else None
        if not attachments:
            raise AcpContentError("cannot deliver assistant image: no attachment store is mounted", "internal")
        ref = block.get("attachment")
        if hasattr(attachments, "read_image"):
            stored = attachments.read_image(ref)
            data_b64 = base64.b64encode(stored.get("data", b"")).decode("ascii")
            return {"type": "image", "data": data_b64, "mimeType": stored.get("mediaType", "image/png")}
        return {"type": "image", "data": "", "mimeType": "image/png"}
    return None
