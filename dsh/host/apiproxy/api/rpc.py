"""
RPC Data Structures & Envelope Models (`@deepseek-ai/dsh-apiproxy/api/rpc`).
Aligned 1:1 with reference `api/rpc.ts` and `api/rpc.schema.ts`.
"""

from typing import Any, Dict, Optional


class RpcId(str):
    """Opaque string ID for RPC correlation."""
    pass


def make_rpc_id(value: str) -> str:
    return str(value)


class ClientRequest:
    """Official client-request envelope sent from browser Web GUI to backend."""

    def __init__(self, rpc_id: str, method: str, payload: Optional[Dict[str, Any]] = None):
        self.type = "client-request"
        self.rpc_id = rpc_id
        self.method = method
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "client-request",
            "rpcId": self.rpc_id,
            "method": self.method,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClientRequest":
        return cls(
            rpc_id=str(data.get("rpcId", "invalid-request")),
            method=str(data.get("method", "")),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
        )


class ServerResponse:
    """Official server-response envelope sent from backend to browser Web GUI."""

    def __init__(self, rpc_id: str, ok: bool, value: Any = None, error: Optional[Dict[str, Any]] = None):
        self.type = "server-response"
        self.rpc_id = rpc_id
        self.ok = ok
        self.value = value
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": self.ok}
        if self.ok:
            result["value"] = self.value
        else:
            result["error"] = self.error or {"code": "internal", "message": "Unknown error", "details": {}}

        return {
            "type": "server-response",
            "rpcId": self.rpc_id,
            "result": result,
        }


class ServerRequest:
    """Official server-request SSE push frame (events, approvals, questions)."""

    def __init__(self, rpc_id: str, method: str, payload: Dict[str, Any]):
        self.type = "server-request"
        self.rpc_id = rpc_id
        self.method = method
        self.payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "server-request",
            "rpcId": self.rpc_id,
            "method": self.method,
            "payload": self.payload,
        }
