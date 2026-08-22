import base64
import os
import shutil
import struct
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.session.session_query import (
    SessionQueryService,
    compile_session_text_filter,
    extract_session_event_text,
    filter_session_event_documents,
    filter_session_results,
    make_snippet,
    materialize_session_event_result_filters,
    materialize_session_result_filters,
    quote_fts_data,
    sanitize_fts_text,
)
from dsh.session.repair import (
    interrupted_turn_closers,
    TOOL_NOT_STARTED,
    TOOL_OUTCOME_UNKNOWN,
)
from dsh.attachment import (
    AttachmentError,
    AttachmentId,
    ImageVariantId,
    LocalAttachmentStore,
    admit_encoded_images,
    decode_base64,
    detect_image,
    is_image_admission_error,
    probe_image,
)


# Helper to generate minimal valid PNG bytes
def make_dummy_png(width=10, height=10):
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = b"\x00\x00\x00\x00"  # mock crc
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    iend_chunk = struct.pack(">I", 0) + b"IEND" + b"\xae\x42\x60\x82"
    return header + ihdr_chunk + iend_chunk


def test_extract_session_event_text_parity():
    # User message text vs reasoning
    event_user = {
        "type": "user/message",
        "data": {
            "content": [
                {"type": "text", "text": "Hello world"},
                {"type": "reasoning", "text": "Hidden thoughts"},
            ]
        },
    }
    extracted = extract_session_event_text(event_user)
    assert extracted == "Hello world"

    # Assistant message
    event_assistant = {
        "type": "assistant/message",
        "data": {
            "message": {
                "content": [
                    {"type": "text", "text": "Response text"},
                    {"type": "reasoning", "text": "Internal reasoning"},
                ]
            }
        },
    }
    assert extract_session_event_text(event_assistant) == "Response text"

    # Tool call & tool result
    event_tcall = {
        "type": "tool/call",
        "data": {"name": "read_file", "arguments": {"path": "test.txt"}},
    }
    assert "read_file" in extract_session_event_text(event_tcall)

    # Turn end error
    event_turn_end = {
        "type": "turn/end",
        "data": {"reason": {"kind": "error", "error": {"message": "Out of memory"}}},
    }
    assert extract_session_event_text(event_turn_end) == "error\nOut of memory"


def test_session_query_filters_and_fts():
    # Text filter compilation
    pat = compile_session_text_filter("  nginx   proxy ")
    assert pat.search("Configure Nginx Proxy server")

    # Range validation
    with pytest.raises(Exception):
        materialize_session_result_filters([{"kind": "created-at", "from": 100, "to": 50}])

    # Filter session results
    records = [
        {"header": {"id": "s1", "cwd": "/app", "createdAt": 1000}, "live": True, "persisted": True},
        {"header": {"id": "s2", "cwd": "/tmp", "createdAt": 2000}, "live": False, "persisted": True},
    ]
    filtered = filter_session_results(records, [{"kind": "cwd", "values": ["/app"]}])
    assert len(filtered) == 1
    assert filtered[0]["header"]["id"] == "s1"

    # FTS helpers
    assert quote_fts_data('hello "world"') == '"hello ""world"""'
    assert sanitize_fts_text("test\0data") == "test\uFFFDdata"
    snippet = make_snippet("This is \uFDD0matching text\uFDD1 in long string", 30)
    assert "matching text" in snippet


def test_session_repair_parity():
    events = [
        {"type": "turn/start", "seq": 0, "time": 1000, "data": {"turn": 1}},
        {"type": "step/start", "seq": 1, "time": 1001, "data": {"turn": 1, "step": 1}},
        {"type": "assistant/message", "seq": 2, "time": 1002, "data": {
            "turn": 1, "step": 1,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool-call", "id": "call-1", "name": "pwsh"}],
            }
        }},
        {"type": "tool/call", "seq": 3, "time": 1003, "data": {"turn": 1, "step": 1, "callId": "call-1"}},
    ]

    closers = interrupted_turn_closers(events)
    assert len(closers) == 3
    tool_res = closers[0]
    assert tool_res["type"] == "tool/result"
    assert tool_res["data"]["error"]["code"] == TOOL_OUTCOME_UNKNOWN
    msg_text = tool_res["data"]["message"]["content"][0]["content"][0]["text"]
    assert "Do not retry blindly." in msg_text
    assert tool_res["sourceEventSeqs"] == [3]


def test_attachment_base64_and_mime():
    png_bytes = make_dummy_png(20, 20)
    b64_png = base64.b64encode(png_bytes).decode("ascii")

    # Canonical base64 check
    decoded = decode_base64(b64_png)
    assert decoded == png_bytes

    # Non-canonical base64 error
    with pytest.raises(AttachmentError) as exc_info:
        decode_base64(b64_png + "===")
    assert exc_info.value.code == "INVALID_IMAGE_BASE64"

    # Image header probe & detect
    meta = probe_image(png_bytes)
    assert meta["mediaType"] == "image/png"
    assert meta["width"] == 20
    assert meta["height"] == 20

    # Image pixel limits
    with pytest.raises(AttachmentError) as exc_info:
        detect_image(png_bytes, limits={"maxPixels": 100})
    assert exc_info.value.code == "IMAGE_TOO_MANY_PIXELS"

    assert is_image_admission_error(exc_info.value)


def test_local_attachment_store():
    temp_dir = tempfile.mkdtemp()
    try:
        ctx = Context()
        store = LocalAttachmentStore(ctx, config={"dshHome": temp_dir})

        png_bytes = make_dummy_png(15, 15)
        b64_png = base64.b64encode(png_bytes).decode("ascii")

        images = [{"data": b64_png, "mediaType": "image/png", "name": "sample.png"}]
        refs = admit_encoded_images(store, images)

        assert len(refs) == 1
        ref = refs[0]
        assert ref["mediaType"] == "image/png"
        assert ref["width"] == 15
        assert ref["height"] == 15
        assert ref["name"] == "sample.png"
        assert ref["attachmentId"].startswith("sha256:")

        # Read back image
        stored = store.read_image(ref)
        assert stored["data"] == png_bytes

        # Read image request variant
        req_img = store.read_image_request(ref, policy={"maxPixels": 10000, "maxBytes": 1000000})
        assert req_img["variantId"].startswith("sha256:")
        assert req_img["bytes"] == len(png_bytes)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
