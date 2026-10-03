"""
Service Definition for the approval capability seam (`ctx.approval`), covering requests, cancellation, audit, and per-session policy.
Missing answerers fail closed; grants apply only to the requested action.
Native port of the pinned `@deepseek-ai/dsh-user-approval` service contract.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.core.scope import scope_target
from dsh.core.abort import AbortController
from dsh.llm.message import create_user_message


OUTCOMES = ("allowed-once", "rejected", "cancelled", "unavailable")
APPROVAL_POLICIES = ("ask", "never")

NEVER_SENTENCE = (
    "Approval prompts are disabled in this session: actions that require approval are rejected automatically "
    "— do not request sandbox escalation (do not set `sandbox_permissions`)."
)
ASK_SENTENCE = (
    "Approval policy: ask. Operations that require approval may ask through the configured answerers; "
    "without an available answerer, the request fails closed."
)


def effective_approval_policy(events: List[Dict[str, Any]]) -> Optional[str]:
    """Fold latest approval/policy from session events."""
    for ev in reversed(events):
        if ev.get("type") == "approval/policy":
            return ev.get("data", {}).get("policy")
    return None


effectiveApprovalPolicy = effective_approval_policy


def has_open_turn(events: List[Dict[str, Any]]) -> bool:
    """Whether the log currently sits inside an open turn."""
    for ev in reversed(events):
        etype = ev.get("type")
        if etype == "turn/start":
            return True
        if etype == "turn/end":
            return False
    return False


def set_approval_policy(session: Any, policy: str) -> None:
    """Append durable approval/policy override to session log."""
    if policy not in APPROVAL_POLICIES:
        raise TypeError('approval policy must be one of "ask" or "never"')
    session.append("approval/policy", {"policy": policy})


setApprovalPolicy = set_approval_policy


class ApprovalService(Service):
    """
    Approval service that applies session policy before answerers and logs every
    ask/outcome pair to the requesting session.
    """

    Config = Schema.object({'policy': Schema.union(['ask', 'never']).default('ask')})

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # Pending answerers remain borrowed after a signal wins, just as the
        # reference's Promise chain does. Keep tasks alive and consume every
        # eventual completion without keeping the caller's decision pending.
        self._answers = set()
        super().__init__(ctx, 'approval')

        if ctx is not None:
            def contribute(scope):
                scope.get('systemPrompt').context({
                    "name": "approval:policy",
                    "order": 115,
                    "text": self._context_text,
                })
            ctx.inject(['systemPrompt'], contribute)

    def _context_text(self, context: Dict[str, Any]) -> str:
        agent = context.get("agent")
        if agent is None:
            return ""
        session = getattr(agent, "session", None)
        if session is None:
            return ""
        policy = self.effective_policy(session)
        return NEVER_SENTENCE if policy == "never" else ASK_SENTENCE

    def effective_policy(self, session: Any) -> str:
        return self.override_of(session) or self.config.get("policy") or "ask"

    effectivePolicy = effective_policy

    def override_of(self, session: Any) -> Optional[str]:
        events = getattr(session, "events", [])
        return effective_approval_policy(events)

    overrideOf = override_of

    def set_policy(self, agent: Any, policy: str) -> None:
        session = getattr(agent, "session", None)
        if session is None:
            return
        previous = self.effective_policy(session)
        if previous == policy:
            return
        set_approval_policy(session, policy)
        if hasattr(agent, "inject"):
            agent.inject(create_user_message({
                "content": [{
                    "type": "text",
                    "text": f'The approval policy changed from "{previous}" to "{policy}" (changed by the user).',
                }],
                "source": {"kind": "plugin", "plugin": "user-approval"},
            }))

    setPolicy = set_policy

    async def request(self, req: Dict[str, Any]) -> str:
        agent = req.get("agent")
        session = getattr(agent, "session", None) if agent else None
        if session is None or not has_open_turn(session.events):
            raise RuntimeError(
                "approval.request() outside an open turn: the approval/asked + approval/decided audit pair "
                "must be turn-enclosed (a bare event between turns is crash-tail garbage on reload). "
                "Ask from inside the turn that needs the decision."
            )

        req_id = str(uuid.uuid4())
        asked_data: Dict[str, Any] = {"id": req_id, "toolName": req.get("toolName", "tool")}
        if "callId" in req:
            asked_data["callId"] = req["callId"]
        if "reason" in req:
            asked_data["reason"] = req["reason"]

        session.append("approval/asked", asked_data)
        outcome = await self.decide(req, session)
        session.append("approval/decided", {"id": req_id, "outcome": outcome})
        return outcome

    async def decide(self, req: Dict[str, Any], session: Any) -> str:
        signal = req.get("signal")
        if isinstance(signal, asyncio.Event):
            controller = AbortController()
            if signal.is_set():
                controller.abort()
                return await self.decide(dict(req, signal=controller.signal), session)
            async def observe():
                await signal.wait()
                controller.abort()
            observer = asyncio.create_task(observe())
            try:
                return await self.decide(dict(req, signal=controller.signal), session)
            finally:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
        if signal is not None and getattr(signal, "aborted", False):
            return "cancelled"

        if self.effective_policy(session) == "never":
            return "rejected"

        async def no_answerer(*args: Any, **kwargs: Any) -> Any:
            return "unavailable"

        async def answer():
            try:
                res = await self.ctx.waterfall("approval/request", req, no_answerer,
                                               caller_ctx=scope_target(req['agent'], req['agent']))
                return res if res in OUTCOMES else "unavailable"
            except (Exception, asyncio.CancelledError):
                return "unavailable"

        if signal is None:
            return await answer()

        decision = asyncio.get_running_loop().create_future()

        def on_abort(_event):
            signal.removeEventListener('abort', on_abort)
            if not decision.done():
                decision.set_result('cancelled')

        def answered(task):
            self._answers.discard(task)
            signal.removeEventListener('abort', on_abort)
            # result() also consumes a late failure after abort/caller task
            # cancellation. No second approval/decided append can occur here.
            outcome = 'unavailable' if task.cancelled() else task.result()
            if not decision.done():
                decision.set_result(outcome)

        signal.addEventListener('abort', on_abort, {'once': True})
        task = asyncio.create_task(answer())
        self._answers.add(task)
        task.add_done_callback(answered)
        try:
            return await decision
        finally:
            signal.removeEventListener('abort', on_abort)


UserApprovalService = ApprovalService


class UserApprovalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-user-approval`: Mounts `ctx.approval` service.
    """

    id = "approval"
    name = "@deepseek-ai/dsh-user-approval"
    Config = ApprovalService.Config

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def apply(self, ctx: Any) -> None:
        ApprovalService(ctx, self.config)

