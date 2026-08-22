"""
Durable attachment vocabulary and type structures.
Aligned 1:1 with `@deepseek-ai/dsh-attachment/types`.
"""

from typing import Any, Dict, List, Optional

ImageMediaType = str  # 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif'


def create_image_attachment_ref(
    attachment_id: str,
    media_type: str,
    bytes_count: int,
    width: int,
    height: int,
    name: Optional[str] = None,
    original_dimensions: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    ref: Dict[str, Any] = {
        "attachmentId": attachment_id,
        "mediaType": media_type,
        "bytes": bytes_count,
        "width": width,
        "height": height,
    }
    if name is not None:
        ref["name"] = name
    if original_dimensions is not None:
        ref["originalDimensions"] = original_dimensions
    return ref


def create_image_attachment_limits(
    max_image_bytes: int = 20 * 1024 * 1024,
    max_images_per_message: int = 20,
    max_message_image_bytes: int = 200 * 1024 * 1024,
    max_image_pixels: int = 64_000_000,
    max_image_dimension: int = 8192,
    media_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if media_types is None:
        media_types = ["image/png", "image/jpeg", "image/webp", "image/gif"]
    return {
        "maxImageBytes": max_image_bytes,
        "maxImagesPerMessage": max_images_per_message,
        "maxMessageImageBytes": max_message_image_bytes,
        "maxImagePixels": max_image_pixels,
        "maxImageDimension": max_image_dimension,
        "mediaTypes": media_types,
    }
