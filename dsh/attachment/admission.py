"""
Wire-form admission of base64-encoded image uploads.
Aligned 1:1 with `@deepseek-ai/dsh-attachment/admission`.
"""

import base64
from typing import Any, Dict, List
from dsh.attachment.error import AttachmentError


def decode_base64(data: str) -> bytes:
    """
    Decode one upload payload while rejecting non-canonical base64 forms.
    """
    if not isinstance(data, str) or len(data) == 0:
        raise AttachmentError("Image upload is not canonical base64.", "INVALID_IMAGE_BASE64")

    try:
        decoded = base64.b64decode(data, validate=True)
        # Re-encode to verify canonical form
        re_encoded = base64.b64encode(decoded).decode("ascii")
        if re_encoded != data:
            raise AttachmentError("Image upload is not canonical base64.", "INVALID_IMAGE_BASE64")
        return decoded
    except Exception as e:
        if isinstance(e, AttachmentError):
            raise e
        raise AttachmentError("Image upload is not canonical base64.", "INVALID_IMAGE_BASE64", cause=e)


def save_input(image: Dict[str, Any]) -> Dict[str, Any]:
    """Store input for one decoded upload."""
    raw_data = image.get("data", "")
    decoded = decode_base64(raw_data)
    result: Dict[str, Any] = {
        "data": decoded,
        "mediaType": image.get("mediaType", "image/png"),
    }
    if "name" in image and image["name"] is not None:
        result["name"] = image["name"]
    return result


def admit_encoded_images(
    attachments: Any,
    images: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Admit one wire image batch: enforce canonical base64 on every member, then
    delegate batch admission to `attachments.save_images`.
    """
    save_inputs = [save_input(img) for img in images]
    return attachments.save_images(save_inputs)
