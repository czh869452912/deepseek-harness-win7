"""
RPC Schema Validation & Payload Parsers (`@deepseek-ai/dsh-apiproxy/api/rpc.schema`).
Aligned 1:1 with reference `api/rpc.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_client_request(body: Any) -> Tuple[bool, Dict[str, Any]]:
    """Validate client-request JSON envelope."""
    if not isinstance(body, dict):
        return False, {"code": "bad-request", "message": "Body is not a JSON object"}

    if body.get("type") == "client-request":
        if not isinstance(body.get("rpcId"), str):
            return False, {"code": "bad-request", "message": "Missing or invalid rpcId"}
        if not isinstance(body.get("method"), str):
            return False, {"code": "bad-request", "message": "Missing or invalid method"}
        return True, {}

    # Allow direct JSON payload requests (lenient mode)
    return True, {}
