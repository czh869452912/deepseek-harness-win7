"""
Fetch Carrier & Unary RPC Handler (`@deepseek-ai/dsh-host-apiproxy/fetch`).
Maps incoming HTTP Requests onto ApiProxy RPC methods and handles SSE/Download GET routes.
Aligned 1:1 with reference `fetch/handler.ts`.
"""

from typing import Any, Dict, Optional, Set
from dsh.host.apiproxy.api.rpc_map import OFFICIAL_RPC_METHODS


def normalize_rpc_method(path: str) -> str:
    """Extract raw RPC method string from `/api/...` path."""
    return path[5:] if path.startswith("/api/") else path
