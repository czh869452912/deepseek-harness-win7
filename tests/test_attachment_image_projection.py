import io
import struct

import pytest
from PIL import Image, PngImagePlugin

from dsh.attachment.local import LocalAttachmentStore, prepare_image_file, request_image_variant_id
from dsh.attachment.error import AttachmentError
from dsh.attachment.image_codec import dimensions


def image_bytes(mode="RGB", size=(300, 200), metadata=False):
    image = Image.new(mode, size, (10, 20, 30, 80) if mode == "RGBA" else (10, 20, 30))
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("private", "discard me")
    image.save(output, "PNG", pnginfo=info)
    return output.getvalue()


@pytest.mark.parametrize("alpha", [False, True])
def test_normalization_strips_metadata_and_request_projection_preserves_alpha(tmp_path, alpha):
    store = LocalAttachmentStore(config={"dshHome": str(tmp_path), "normalizedImageMaxPixels": 10000})
    data = image_bytes("RGBA" if alpha else "RGB", metadata=True)
    ref = store.save_image({"data": data, "mediaType": "image/png", "name": "image.png"})
    assert ref["width"] * ref["height"] <= 10000
    assert ref["originalDimensions"] == {"width": 300, "height": 200}
    stored = store.read_image(ref)
    with Image.open(io.BytesIO(stored["data"])) as normalized:
        assert "private" not in normalized.info
        assert ("A" in normalized.getbands()) is alpha
    policy = {"maxPixels": 1000, "maxBytes": 10000}
    request = store.read_image_request(ref, policy)
    assert request["width"] * request["height"] <= 1000
    assert request["hasAlpha"] is alpha
    assert request["variantId"] != request_image_variant_id(ref, dict(policy, maxPixels=900))
    assert store.read_image_request(ref, policy)["data"] == request["data"]
    cache = next((tmp_path / "attachments" / "v1" / "request-images").rglob(str(request["variantId"])[7:]))
    cache.write_bytes(b"corrupt")
    assert store.read_image_request(ref, policy)["data"] == request["data"]


def test_admission_rejects_valid_header_without_decodable_pixels(tmp_path):
    store = LocalAttachmentStore(config={"dshHome": str(tmp_path)})
    header_only = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0) + b"\0" * 4
    with pytest.raises(AttachmentError) as caught:
        store.save_image({"data": header_only, "mediaType": "image/png"})
    assert caught.value.code == "INVALID_IMAGE"
    assert not list(tmp_path.rglob("objects"))


@pytest.mark.parametrize("width,height,budget", [(1, 10000, 50), (10000, 1, 50), (301, 200, 1000), (200, 301, 1000)])
def test_extreme_aspect_ratio_projection_stays_inside_hard_pixel_budget(width, height, budget):
    projected = dimensions(width, height, budget)
    assert projected[0] * projected[1] <= budget
    assert 1 <= projected[0] <= width and 1 <= projected[1] <= height


def test_small_clean_image_is_byte_identical_and_tiny_byte_target_uses_smallest_ladder(tmp_path):
    store = LocalAttachmentStore(config={"dshHome": str(tmp_path)})
    data = image_bytes(size=(10, 10))
    ref = store.save_image({"data": data, "mediaType": "image/png"})
    assert store.read_image(ref)["data"] == data
    assert store.read_image_request(ref, {"maxPixels": 1000, "maxBytes": 1000})["data"] == data
    projected = store.read_image_request(ref, {"maxPixels": 1000, "maxBytes": 1})
    assert projected["width"] == 10 and projected["height"] == 10
    assert projected["mediaType"] == "image/jpeg"
    assert projected["bytes"] > 1  # Upstream retains smallest quality; route enforces hard byte cap.
