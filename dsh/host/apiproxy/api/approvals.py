"""
Approvals Domain Handler (`@deepseek-ai/dsh-apiproxy/api/approvals`).
Aligned 1:1 with reference `api/approvals.ts`.
"""

from typing import Any, Dict


class ApprovalsDomainHandler:
    def __init__(self, ctx: Any, pending_requests: Dict[str, Any], broadcast_mux: Any):
        self.ctx = ctx
        self._pending = pending_requests
        self._broadcast_mux = broadcast_mux

    async def handle_respond(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp_rpc_id = payload.get("rpcId")
        result = payload.get("result", {})
        ok = result.get("ok", True) if isinstance(result, dict) else True
        value = result.get("value") if isinstance(result, dict) else payload.get("answer") or payload.get("outcome")

        if not resp_rpc_id or resp_rpc_id not in self._pending:
            return {"accepted": False, "reason": "not-pending"}

        pending_item = self._pending.pop(resp_rpc_id)
        fut = pending_item.get("future") if isinstance(pending_item, dict) else pending_item
        sid = pending_item.get("sessionId", "default-session") if isinstance(pending_item, dict) else "default-session"
        item_type = pending_item.get("type", "approval") if isinstance(pending_item, dict) else "approval"

        if fut and hasattr(fut, "set_result") and not fut.done():
            fut.set_result(value if ok else None)

        if item_type == "question":
            outcome = "answered" if ok else "cancelled"
            await self._broadcast_mux({
                "type": "question/resolved",
                "sessionId": sid,
                "questionRpcId": resp_rpc_id,
                "outcome": outcome,
            })
        else:
            outcome = value if (isinstance(value, str) and value in ("approved", "rejected")) else ("approved" if ok else "rejected")
            await self._broadcast_mux({
                "type": "approval/resolved",
                "sessionId": sid,
                "approvalId": resp_rpc_id,
                "outcome": outcome,
            })

        return {"accepted": True}
