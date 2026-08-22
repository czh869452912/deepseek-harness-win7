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
        sid = payload.get("sessionId", "default-session")
        answer = payload.get("answer")
        outcome = payload.get("outcome")

        if resp_rpc_id and resp_rpc_id in self._pending:
            fut = self._pending.pop(resp_rpc_id)
            if not fut.done():
                fut.set_result(answer or outcome or True)

        if answer is not None:
            await self._broadcast_mux({
                "type": "question/resolved",
                "sessionId": sid,
                "questionRpcId": resp_rpc_id,
                "outcome": "answered",
            })
        elif outcome is not None:
            await self._broadcast_mux({
                "type": "approval/resolved",
                "sessionId": sid,
                "approvalId": payload.get("approvalId", resp_rpc_id),
                "outcome": outcome,
            })

        return {"ok": True, "accepted": True, "success": True}
