"""
Approvals Domain Handler (`@deepseek-ai/dsh-apiproxy/api/approvals`).
Aligned 1:1 with reference `api/approvals.ts` and `api-proxy.ts` respond().
"""

from typing import Any, Dict
from dsh.host.apiproxy.api.questions import matches_questions


class ApprovalsDomainHandler:
    """Handler for POST /api/respond resolving approvals and user questions."""

    def __init__(self, ctx: Any, pending_requests: Dict[str, Any], broadcast_mux: Any):
        self.ctx = ctx
        self._pending = pending_requests
        self._broadcast_mux = broadcast_mux

    async def handle_respond(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp_rpc_id = payload.get("rpcId")
        if not resp_rpc_id:
            return {"accepted": False, "reason": "bad-response"}

        if resp_rpc_id not in self._pending:
            return {"accepted": False, "reason": "not-pending"}

        pending_item = self._pending.get(resp_rpc_id)
        if not isinstance(pending_item, dict):
            return {"accepted": False, "reason": "not-pending"}

        item_type = pending_item.get("type", "approval")
        result = payload.get("result", {})
        is_ok = result.get("ok", True) if isinstance(result, dict) else (payload.get("ok", True))
        value = result.get("value") if isinstance(result, dict) else payload.get("value", payload.get("answer") or payload.get("outcome"))

        if item_type == "question":
            if not is_ok:
                err = result.get("error", {}) if isinstance(result, dict) else {}
                err_code = err.get("code") if isinstance(err, dict) else None
                if err_code != "cancelled":
                    return {"accepted": False, "reason": "bad-response"}

                self._pending.pop(resp_rpc_id, None)
                fut = pending_item.get("future")
                if fut and hasattr(fut, "set_exception") and not fut.done():
                    from dsh.interaction.user_questions import UserQuestionError
                    fut.set_exception(UserQuestionError("the user cancelled ask_user_question", "ASK_CANCELLED"))
                elif fut and hasattr(fut, "set_result") and not fut.done():
                    fut.set_result(None)

                await self._broadcast_mux({
                    "type": "question/resolved",
                    "sessionId": pending_item.get("sessionId", "default-session"),
                    "questionRpcId": resp_rpc_id,
                    "outcome": "cancelled",
                })
                return {"accepted": True}

            if not isinstance(value, dict):
                return {"accepted": False, "reason": "bad-response"}

            # Check matches_questions
            question_payload = {
                "sessionId": value.get("sessionId") or pending_item.get("sessionId"),
                "answer": value.get("answer", value),
            }
            if not matches_questions(question_payload, pending_item):
                return {"accepted": False, "reason": "bad-response"}

            self._pending.pop(resp_rpc_id, None)
            fut = pending_item.get("future")
            if fut and hasattr(fut, "set_result") and not fut.done():
                fut.set_result(question_payload["answer"])

            await self._broadcast_mux({
                "type": "question/resolved",
                "sessionId": pending_item.get("sessionId", "default-session"),
                "questionRpcId": resp_rpc_id,
                "outcome": "answered",
            })
            return {"accepted": True}

        else:
            # Approval handling
            if not is_ok:
                return {"accepted": False, "reason": "bad-response"}

            val_outcome = None
            if isinstance(value, str):
                val_outcome = value
            elif isinstance(value, dict):
                appr_id = value.get("approvalId")
                sess_id = value.get("sessionId")
                if (appr_id and pending_item.get("approvalId") and appr_id != pending_item.get("approvalId")) or \
                   (sess_id and pending_item.get("sessionId") and sess_id != pending_item.get("sessionId")):
                    return {"accepted": False, "reason": "bad-response"}
                val_outcome = value.get("outcome")

            outcome = "allowed-once"
            if val_outcome in ("allowed-once", "rejected", "cancelled", "unavailable"):
                outcome = val_outcome
            elif val_outcome == "approved":
                outcome = "allowed-once"

            self._pending.pop(resp_rpc_id, None)
            fut = pending_item.get("future")
            if fut and hasattr(fut, "set_result") and not fut.done():
                fut.set_result(outcome)

            await self._broadcast_mux({
                "type": "approval/resolved",
                "sessionId": pending_item.get("sessionId", "default-session"),
                "approvalId": resp_rpc_id,
                "outcome": outcome,
            })
            return {"accepted": True}
