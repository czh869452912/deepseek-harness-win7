"""
User approval service (`ctx.approval`): gatekeeper for tool calls and dangerous actions.
Aligned 1:1 with official `@deepseek-ai/dsh-user-approval`.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class UserApprovalService:
    """Approval service mounted at `ctx.approval`."""

    def __init__(self, ctx: Any, policy: str = "ask"):
        self.ctx = ctx
        self.policy = policy  # "ask" | "always" | "never"
        self._pending: Dict[str, asyncio.Future] = {}

    def set_policy(self, policy: str) -> None:
        self.policy = policy

    async def request_approval(
        self,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        timeout_s: float = 120.0,
    ) -> bool:
        if self.policy == "always":
            return True
        if self.policy == "never":
            return False

        req_id = f"appr-{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut

        if hasattr(self.ctx, "emit"):
            self.ctx.emit("approval/requested", {
                "requestId": req_id,
                "action": action,
                "details": details or {},
                "timestamp": int(time.time() * 1000),
            })

        try:
            res = await asyncio.wait_for(fut, timeout=timeout_s)
            return bool(res)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(req_id, None)

    def decide(self, request_id: str, approved: bool) -> bool:
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(approved)
            return True
        return False


class UserApprovalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-user-approval`: Mounts `ctx.approval` service.
    """

    id = "approval"
    name = "@deepseek-ai/dsh-user-approval"

    def apply(self, ctx: Any) -> None:
        policy = self.config.get("policy", "ask")
        svc = UserApprovalService(ctx, policy=policy)
        ctx.set_service("approval", svc)
