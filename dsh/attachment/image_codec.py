"""Python 3.8 image decoding and deterministic sRGB request projections.

Pillow replaces upstream Sharp on the Win7 portable runtime. Encoder identity
is part of the variant key: bytes from different codecs must never share a key.
"""
import io
import math

from PIL import Image, ImageCms, ImageOps

from dsh.attachment.error import AttachmentError

QUALITIES = (85, 75, 60)


def dimensions(width, height, max_pixels):
    scale = min(1, math.sqrt(max_pixels / (width * height)))
    if scale == 1:
        return width, height
    landscape = width >= height
    major, minor = (width, height) if landscape else (height, width)
    projected = max(1, int(major * scale))
    other = max(1, int(projected * minor / major + 0.5))
    while projected * other > max_pixels and projected > 1:
        projected -= 1
        other = max(1, int(projected * minor / major + 0.5))
    return (projected, other) if landscape else (other, projected)


def decode(data):
    try:
        # verify walks PNG checksums; load forces compressed-pixel validation.
        with Image.open(io.BytesIO(data)) as checked:
            checked.verify()
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            source.load()
            return source.copy()
    except Exception as error:
        raise AttachmentError("Unsupported or malformed image data.", "INVALID_IMAGE", cause=error)


def metadata(data, header):
    image = decode(data)
    result = dict(header)
    result.update(width=image.width, height=image.height,
                  hasAlpha="A" in image.getbands() or "transparency" in image.info,
                  space="srgb" if image.mode in ("RGB", "RGBA", "P", "L", "LA") else image.mode.lower())
    if image.info.get("icc_profile") or image.info.get("exif") or image.getexif():
        result["carriesMetadata"] = True
    return result


def encode(data, width, height, max_bytes):
    image = ImageOps.exif_transpose(decode(data))
    alpha = "A" in image.getbands() or "transparency" in image.info
    profile = image.info.get("icc_profile")
    if profile:
        try:
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                             ImageCms.createProfile("sRGB"), outputMode="RGBA" if alpha else "RGB")
        except Exception as error:
            raise AttachmentError("Image color profile cannot be converted to sRGB.", "ATTACHMENT_WRITE_FAILED", cause=error)
    elif image.mode.startswith("I"):
        # Pillow represents 16-bit grayscale PNG as integer pixels; explicit
        # scaling avoids clipping nearly every source pixel to white.
        image = image.point(lambda pixel: pixel / 257).convert("L").convert("RGB")
    else:
        image = image.convert("RGBA" if alpha else "RGB")
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    image.info.clear()
    smallest = None
    for quality in QUALITIES:
        output = io.BytesIO()
        image.save(output, format="WEBP" if alpha else "JPEG", quality=quality, **({"method": 0} if alpha else {}))
        candidate = {"data": output.getvalue(), "mediaType": "image/webp" if alpha else "image/jpeg",
                     "width": image.width, "height": image.height}
        if len(candidate["data"]) <= max_bytes:
            return candidate
        if smallest is None or len(candidate["data"]) < len(smallest["data"]):
            smallest = candidate
    return smallest
