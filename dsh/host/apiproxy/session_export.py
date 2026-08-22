"""
Session Log Exporter (`@deepseek-ai/dsh-host-apiproxy/session-export`).
Exports session history events as ZIP or NDJSON stream.
Aligned 1:1 with reference `session-export.ts`.
"""

import io
import json
from typing import Any, Dict, List, Optional
import zipfile


def export_session_zip(session_id: str, events: List[Dict[str, Any]], compression_level: int = 6) -> bytes:
    """
    Pack session events into a ZIP archive containing `session.jsonl`.
    Uses standard Python `zipfile` library (Windows 7 SP1 & Python 3.8 compatible).
    """
    buf = io.BytesIO()
    lines = [json.dumps(ev, ensure_ascii=False, default=str) for ev in events]
    ndjson_content = "\n".join(lines).encode("utf-8")

    zip_compression = zipfile.ZIP_DEFLATED if compression_level > 0 else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, mode="w", compression=zip_compression) as zf:
        zf.writestr(f"session-{session_id}/events.ndjson", ndjson_content)
        manifest = {
            "sessionId": session_id,
            "eventCount": len(events),
            "version": "1.0.0",
        }
        zf.writestr(f"session-{session_id}/manifest.json", json.dumps(manifest, indent=2))

    return buf.getvalue()


def export_session_ndjson(session_id: str, events: List[Dict[str, Any]]) -> bytes:
    """Export session events directly as raw NDJSON bytes."""
    lines = [json.dumps(ev, ensure_ascii=False, default=str) for ev in events]
    return "\n".join(lines).encode("utf-8")
