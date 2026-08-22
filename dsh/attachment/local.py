"""
Local durable attachment backend rooted below DSH_HOME.
Aligned 1:1 with `@deepseek-ai/dsh-attachment-local`.
"""

import hashlib
import json
import os
import re
import struct
import uuid
from typing import Any, Dict, List, Optional, Tuple

from dsh.attachment.brand import AttachmentId, ImageVariantId
from dsh.attachment.error import AttachmentError
from dsh.attachment.store import AttachmentStore
from dsh.attachment.types import create_image_attachment_limits

DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_IMAGES_PER_MESSAGE = 20
DEFAULT_MAX_MESSAGE_IMAGE_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 64_000_000
DEFAULT_MAX_IMAGE_DIMENSION = 8192
DEFAULT_NORMALIZED_IMAGE_MAX_DIMENSION = 2048
DEFAULT_NORMALIZED_IMAGE_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_IMAGE_COMPRESSION_CONCURRENCY = 2
MAX_IMAGE_COMPRESSION_CONCURRENCY = 8

ID_PATTERN = re.compile(r"^sha256:([a-f0-9]{64})$")


def digest_bytes(data: bytes) -> str:
    """Compute sha256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def display_name(value: Optional[str]) -> Optional[str]:
    """Clean and sanitize display name from potential file paths."""
    if value is None:
        return None
    leaf = value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    clean = re.sub(r"[\x00-\x1f\x7f]", "", leaf).strip()[:255]
    return clean if clean != "" else None


def ensure_reference(ref: Dict[str, Any]) -> str:
    """Validate and extract 64-hex sha256 digest from an attachment reference."""
    att_id = str(ref.get("attachmentId", ""))
    match = ID_PATTERN.match(att_id)
    if not match:
        raise AttachmentError("Attachment reference is invalid.", "INVALID_ATTACHMENT_REF")
    return match.group(1)


def probe_image(data: bytes) -> Dict[str, Any]:
    """
    Parse a supported raster's header and return its intrinsic metadata without full decode.
    Supports PNG, JPEG, WebP, GIF.
    """
    if not data or len(data) == 0:
        raise AttachmentError("Image is empty.", "INVALID_IMAGE")

    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 30:
            raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE")
        width, height = struct.unpack(">II", data[16:24])
        bit_depth = data[24]
        color_type = data[25]
        has_alpha = color_type in (4, 6) or (b"tRNS" in data)
        carries_metadata = any(k in data for k in (b"eXIF", b"tEXt", b"zTXt", b"iTXt", b"iCCP"))
        depth = "ushort" if bit_depth == 16 else "uchar"
        return {
            "mediaType": "image/png",
            "width": width,
            "height": height,
            "animated": b"acTL" in data,
            "carriesMetadata": carries_metadata,
            "depth": depth,
            "space": "srgb",
            "hasAlpha": has_alpha,
        }

    # JPEG
    if data.startswith(b"\xff\xd8"):
        offset = 2
        width, height = 0, 0
        has_sof = False
        while offset < len(data) - 1:
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if marker in (0xD8, 0xD9, 0x00):
                offset += 2
                continue
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if offset + 9 <= len(data):
                    height, width = struct.unpack(">HH", data[offset + 5:offset + 9])
                    has_sof = True
                    break
            offset += 2
            if offset + 2 <= len(data):
                seg_len = struct.unpack(">H", data[offset:offset + 2])[0]
                offset += seg_len
        if not has_sof or width <= 0 or height <= 0:
            raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE")
        carries_metadata = any(k in data for k in (b"\xff\xe1", b"\xff\xed", b"\xff\xee"))
        return {
            "mediaType": "image/jpeg",
            "width": width,
            "height": height,
            "animated": False,
            "carriesMetadata": carries_metadata,
            "depth": "uchar",
            "space": "srgb",
            "hasAlpha": False,
        }

    # GIF
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        if len(data) < 10:
            raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE")
        width, height = struct.unpack("<HH", data[6:10])
        descriptors = data.count(b"\x2c")
        animated = descriptors > 1
        has_alpha = b"\x21\xf9" in data
        return {
            "mediaType": "image/gif",
            "width": width,
            "height": height,
            "animated": animated,
            "carriesMetadata": True,
            "depth": "uchar",
            "space": "srgb",
            "hasAlpha": has_alpha,
        }

    # WebP
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        if len(data) < 20:
            raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE")
        chunk_type = data[12:16]
        width, height = 0, 0
        animated = False
        has_alpha = False
        if chunk_type == b"VP8 ":
            if len(data) >= 30:
                raw = data[26:30]
                width = struct.unpack("<H", raw[0:2])[0] & 0x3FFF
                height = struct.unpack("<H", raw[2:4])[0] & 0x3FFF
        elif chunk_type == b"VP8L":
            if len(data) >= 25:
                bits = struct.unpack("<I", data[21:25])[0]
                width = (bits & 0x3FFF) + 1
                height = ((bits >> 14) & 0x3FFF) + 1
                has_alpha = bool((bits >> 28) & 1)
        elif chunk_type == b"VP8X":
            if len(data) >= 30:
                flags = data[20]
                has_alpha = bool(flags & 0x10)
                animated = bool(flags & 0x02)
                width = 1 + (data[24] | (data[25] << 8) | (data[26] << 16))
                height = 1 + (data[27] | (data[28] << 8) | (data[29] << 16))
        if width <= 0 or height <= 0:
            raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE")
        return {
            "mediaType": "image/webp",
            "width": width,
            "height": height,
            "animated": animated,
            "carriesMetadata": chunk_type == b"VP8X",
            "depth": "uchar",
            "space": "srgb",
            "hasAlpha": has_alpha,
        }

    raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE")


def detect_image(data: bytes, limits: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """
    Fully inspect image header and enforce dimension / pixel limits.
    """
    metadata = probe_image(data)
    width = metadata["width"]
    height = metadata["height"]
    pixels = width * height

    if limits:
        max_pixels = limits.get("maxPixels")
        if max_pixels is not None and pixels > max_pixels:
            raise AttachmentError("Image exceeds the configured decoded-pixel limit.", "IMAGE_TOO_MANY_PIXELS")

        max_dim = limits.get("maxDimension")
        if max_dim is not None and max(width, height) > max_dim:
            raise AttachmentError("Image exceeds the configured per-side pixel limit.", "IMAGE_DIMENSION_TOO_LARGE")

    return metadata


def inspect_metadata(
    data: bytes,
    declared_media_type: str,
    limits: Dict[str, Any],
) -> Dict[str, Any]:
    """Inspect image bytes and verify declared media type match."""
    if len(data) == 0:
        raise AttachmentError("Image is empty.", "INVALID_IMAGE")

    detected = detect_image(
        data,
        limits={
            "maxPixels": limits.get("maxImagePixels", DEFAULT_MAX_IMAGE_PIXELS),
            "maxDimension": limits.get("maxImageDimension", DEFAULT_MAX_IMAGE_DIMENSION),
        },
    )
    if detected["mediaType"] != declared_media_type:
        raise AttachmentError("Declared image type does not match its bytes.", "IMAGE_TYPE_MISMATCH")
    return detected


def can_pass_through_normalization(
    detected: Dict[str, Any],
    bytes_len: int,
    policy: Dict[str, int],
) -> bool:
    """Check whether image bytes already satisfy normalization requirements."""
    return (
        detected["mediaType"] != "image/gif"
        and not detected.get("animated", False)
        and not detected.get("carriesMetadata", False)
        and detected.get("depth") == "uchar"
        and detected.get("space") == "srgb"
        and bytes_len <= policy.get("maxBytes", DEFAULT_NORMALIZED_IMAGE_MAX_BYTES)
        and max(detected["width"], detected["height"]) <= policy.get("maxDimension", DEFAULT_NORMALIZED_IMAGE_MAX_DIMENSION)
    )


def prepare_image_file(
    input_data: Dict[str, Any],
    limits: Dict[str, Any],
    policy: Dict[str, int],
) -> Dict[str, Any]:
    """Decode, normalize, and verify one submitted image."""
    data = input_data.get("data", b"")
    max_bytes = limits.get("maxImageBytes", DEFAULT_MAX_IMAGE_BYTES)
    if len(data) > max_bytes:
        raise AttachmentError("Image exceeds the configured byte limit.", "IMAGE_TOO_LARGE")

    declared_type = input_data.get("mediaType", "image/png")
    detected = inspect_metadata(data, declared_type, limits)

    sha256 = digest_bytes(data)
    name = display_name(input_data.get("name"))

    ref: Dict[str, Any] = {
        "attachmentId": AttachmentId(f"sha256:{sha256}"),
        "mediaType": detected["mediaType"],
        "width": detected["width"],
        "height": detected["height"],
        "bytes": len(data),
    }
    if name is not None:
        ref["name"] = name

    return {"data": data, "ref": ref}


def object_path(root: str, sha256: str) -> str:
    """Path to stored object under root."""
    return os.path.join(root, "objects", sha256[:2], sha256)


def commit_prepared_image_file(root: str, prepared: Dict[str, Any]) -> Dict[str, Any]:
    """Publish one already verified normalized image below storage root."""
    data = prepared["data"]
    ref = prepared["ref"]
    sha256 = ensure_reference(ref)

    if digest_bytes(data) != sha256 or len(data) != ref["bytes"]:
        raise AttachmentError("Prepared attachment bytes do not match their reference.", "ATTACHMENT_CORRUPT")

    bucket = os.path.join(root, "objects", sha256[:2])
    staging = os.path.join(root, "tmp")
    os.makedirs(bucket, exist_ok=True)
    os.makedirs(staging, exist_ok=True)

    temp_path = os.path.join(staging, str(uuid.uuid4()))
    target = object_path(root, sha256)

    try:
        with open(temp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        if not os.path.exists(target):
            try:
                os.replace(temp_path, target)
            except Exception:
                if not os.path.exists(target):
                    raise
        else:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        if isinstance(e, AttachmentError):
            raise e
        raise AttachmentError("Unable to persist image attachment.", "ATTACHMENT_WRITE_FAILED", cause=e)

    return ref


def request_image_variant_id(ref: Dict[str, Any], policy: Dict[str, Any]) -> str:
    """Compute deterministic variant ID for model request."""
    desc = json.dumps({
        "transformVersion": "request-image-v4",
        "attachmentId": ref.get("attachmentId"),
        "routePixelBudget": policy.get("maxPixels", 64_000_000),
        "encodedByteBudget": policy.get("maxBytes", 4 * 1024 * 1024),
    }, sort_keys=True)
    return ImageVariantId(f"sha256:{hashlib.sha256(desc.encode('utf-8')).hexdigest()}")


class LocalAttachmentStore(AttachmentStore):
    """
    Persistent content-addressed local attachment store rooted below DSH_HOME.
    """

    id = "attachment-local"
    name = "@deepseek-ai/dsh-attachment-local"

    def __init__(self, ctx: Any = None, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(ctx)
        cfg = config or {}
        dsh_home = cfg.get("dshHome") or os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh")
        self.root = os.path.abspath(os.path.join(dsh_home, "attachments", "v1"))

        self._image_limits = create_image_attachment_limits(
            max_image_bytes=cfg.get("maxImageBytes", DEFAULT_MAX_IMAGE_BYTES),
            max_images_per_message=cfg.get("maxImagesPerMessage", DEFAULT_MAX_IMAGES_PER_MESSAGE),
            max_message_image_bytes=cfg.get("maxMessageImageBytes", DEFAULT_MAX_MESSAGE_IMAGE_BYTES),
            max_image_pixels=cfg.get("maxImagePixels", DEFAULT_MAX_IMAGE_PIXELS),
            max_image_dimension=cfg.get("maxImageDimension", DEFAULT_MAX_IMAGE_DIMENSION),
        )
        self.normalization_policy = {
            "maxDimension": cfg.get("normalizedImageMaxDimension", DEFAULT_NORMALIZED_IMAGE_MAX_DIMENSION),
            "maxBytes": cfg.get("normalizedImageMaxBytes", DEFAULT_NORMALIZED_IMAGE_MAX_BYTES),
        }

    @property
    def image_limits(self) -> Dict[str, Any]:
        return self._image_limits

    def validate_image(self, input_data: Dict[str, Any]) -> None:
        data = input_data.get("data", b"")
        if len(data) > self.image_limits["maxImageBytes"]:
            raise AttachmentError("Image exceeds the configured byte limit.", "IMAGE_TOO_LARGE")
        inspect_metadata(data, input_data.get("mediaType", "image/png"), self.image_limits)

    def save_image(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        prepared = prepare_image_file(input_data, self.image_limits, self.normalization_policy)
        return commit_prepared_image_file(self.root, prepared)

    def read_image(self, ref: Dict[str, Any], signal: Any = None) -> Dict[str, Any]:
        sha256 = ensure_reference(ref)
        target = object_path(self.root, sha256)
        if not os.path.exists(target):
            raise AttachmentError("Attachment object is missing.", "ATTACHMENT_NOT_FOUND")

        try:
            with open(target, "rb") as f:
                data = f.read()
        except Exception as e:
            raise AttachmentError("Unable to read image attachment.", "ATTACHMENT_READ_FAILED", cause=e)

        if digest_bytes(data) != sha256:
            raise AttachmentError("Stored attachment failed integrity verification.", "ATTACHMENT_CORRUPT")

        metadata = probe_image(data)
        if (
            metadata["mediaType"] != ref.get("mediaType")
            or len(data) != ref.get("bytes")
            or metadata["width"] != ref.get("width")
            or metadata["height"] != ref.get("height")
        ):
            raise AttachmentError("Stored attachment metadata does not match its reference.", "ATTACHMENT_CORRUPT")

        return {"ref": ref, "data": data}

    def read_image_request(
        self, ref: Dict[str, Any], policy: Dict[str, Any], signal: Any = None
    ) -> Dict[str, Any]:
        variant_id = request_image_variant_id(ref, policy)
        stored = self.read_image(ref, signal=signal)

        return {
            "variantId": variant_id,
            "attachment": ref,
            "data": stored["data"],
            "mediaType": ref["mediaType"],
            "bytes": len(stored["data"]),
            "width": ref["width"],
            "height": ref["height"],
            "depth": "uchar",
            "space": "srgb",
            "hasAlpha": probe_image(stored["data"]).get("hasAlpha", False),
        }
