"""
ACP Server & Plugin matching reference/packages/acp/acp/src/index.ts
"""
import uuid
from typing import Any, Callable, Dict, List, Optional
from dsh.acp.codec import turn_end_to_stop_reason
from dsh.acp.content import AcpContentError, admit_acp_prompt, assistant_block_to_acp, supports_acp_image_prompts
from dsh.cordis.plugin import Plugin


class SessionRecord:
    def __init__(self, agent: Any, dispose_fn: Optional[Callable[[], Any]] = None):
        self.agent = agent
        self.dispose_fn = dispose_fn
        self.inflight_prompt: Optional[Dict[str, Any]] = None


class AcpPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-acp`: Automation-only Agent Client Protocol server bridge.
    """
    id = "acp"
    name = "@deepseek-ai/dsh-acp"
    inject = ["agents"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.config = config or {}
        self.sessions: Dict[str, SessionRecord] = {}
        self.closed: bool = False
        self.image_prompt_enabled: bool = False

    def apply(self, ctx: Any) -> None:
        if hasattr(ctx, "on"):
            ctx.on("session/event", self._on_session_event)
            ctx.on("agent/inbox/claimed", self._on_inbox_claimed)
            ctx.on("agent/error", self._on_agent_error)
            ctx.on("approval/request", self._on_approval_request)

        def disposer():
            self.closed = True
            for session in list(self.sessions.values()):
                if session.dispose_fn:
                    try:
                        session.dispose_fn()
                    except Exception:
                        pass
            self.sessions.clear()

        if hasattr(ctx, "effect"):
            ctx.effect(disposer)

    async def initialize(self, ctx: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        p = self.config.get("provider")
        m = self.config.get("model")
        self.image_prompt_enabled = supports_acp_image_prompts(ctx, p, m)
        return {
            "protocolVersion": "1.0",
            "agentInfo": {"name": "deepseek-harness-acp", "version": "0.0.1"},
            "agentCapabilities": {
                "promptCapabilities": {
                    "image": self.image_prompt_enabled,
                    "audio": False,
                    "embeddedContext": False,
                }
            },
            "authMethods": [],
        }

    async def authenticate(self, ctx: Any, params: Dict[str, Any]) -> None:
        pass

    async def new_session(self, ctx: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.closed:
            raise RuntimeError("the ACP bridge has been disposed")
        cwd = params.get("cwd", "")
        if not cwd:
            raise ValueError("cwd must be an absolute path")
        if params.get("additionalDirectories"):
            raise ValueError("additionalDirectories is not supported")
        if params.get("mcpServers"):
            raise ValueError("mcpServers is not supported")

        session_id = f"acp-session-{uuid.uuid4().hex[:8]}"
        agents_svc = ctx.get("agents") if hasattr(ctx, "get") else None
        if agents_svc and hasattr(agents_svc, "create"):
            handle = await agents_svc.create(session_id=session_id, meta={"cwd": cwd})
            agent = getattr(handle, "agent", handle)
            dispose_fn = getattr(handle, "dispose", None)
        else:
            agent = getattr(ctx, "agent", None)
            dispose_fn = None

        rec = SessionRecord(agent=agent, dispose_fn=dispose_fn)
        self.sessions[session_id] = rec
        return {"sessionId": session_id}

    async def prompt(self, ctx: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.closed:
            raise RuntimeError("the ACP bridge has been disposed")
        session_id = params.get("sessionId")
        if session_id not in self.sessions:
            raise ValueError(f"unknown session: {session_id}")

        rec = self.sessions[session_id]
        if rec.inflight_prompt is not None:
            raise ValueError("a prompt is already in flight for this session")

        prompt_blocks = params.get("prompt", [])
        content = admit_acp_prompt(ctx, rec.agent, prompt_blocks, self.image_prompt_enabled)

        msg = {"id": f"msg-{uuid.uuid4().hex[:8]}", "role": "user", "content": content}
        rec.inflight_prompt = {"msg_id": msg["id"], "done": False, "stop_reason": "end_turn"}

        if rec.agent and hasattr(rec.agent, "followup"):
            rec.agent.followup(msg)

        if rec.agent and hasattr(rec.agent, "when_idle"):
            res = rec.agent.when_idle()
            if hasattr(res, "__await__"):
                await res

        stop_reason = rec.inflight_prompt.get("stop_reason", "end_turn")
        rec.inflight_prompt = None
        return {"stopReason": stop_reason}

    async def cancel(self, ctx: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        if session_id in self.sessions:
            rec = self.sessions[session_id]
            if rec.inflight_prompt:
                rec.inflight_prompt["stop_reason"] = "cancelled"
            if rec.agent and hasattr(rec.agent, "cancel"):
                rec.agent.cancel({"kind": "user"})

    def _on_session_event(self, session: Any, event: Dict[str, Any]) -> None:
        e_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
        data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
        if e_type == "turn/end":
            reason = data.get("reason", {})
            stop_reason = turn_end_to_stop_reason(reason)
            for rec in self.sessions.values():
                if rec.inflight_prompt:
                    rec.inflight_prompt["stop_reason"] = stop_reason

    def _on_inbox_claimed(self, payload: Dict[str, Any]) -> None:
        pass

    def _on_agent_error(self, payload: Dict[str, Any]) -> None:
        pass

    def _on_approval_request(self, request: Any, next_fn: Any) -> Any:
        return next_fn()
