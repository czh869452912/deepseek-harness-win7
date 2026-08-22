"""
Events Domain Handler & SSE Formatters (`@deepseek-ai/dsh-apiproxy/api/events`).
Aligned 1:1 with reference `api/events.ts`.
"""

import json
import uuid
from typing import Any, Dict, Optional


def format_sse_frame(payload: Dict[str, Any], rpc_id: Optional[str] = None) -> bytes:
    """Format SSE data line according to official ServerRequest schema."""
    frame_rpc_id = rpc_id or str(uuid.uuid4())
    frame_type = payload.get("type", "unknown")
    envelope = {
        "type": "server-request",
        "rpcId": frame_rpc_id,
        "method": frame_type,
        "payload": payload,
    }
    return f"data: {json.dumps(envelope, ensure_ascii=False, default=str)}\n\n".encode("utf-8")
