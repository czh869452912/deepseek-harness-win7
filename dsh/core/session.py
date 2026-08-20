"""
Event-Sourced Session Service and Session Store mounted at `ctx.sessions`.
Maintains append-only session log, SurfaceManager projection, and EpochHeader/RequestContext folding.
"""

import time
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin
from dsh.core.surface import (
    SurfaceManager,
    derive_event_message,
    is_surface_eligible_type,
)

SESSION_FORMAT_VERSION = 1
SessionEvent = Dict[str, Any]


class SessionHeader:
    """Immutable storage metadata for a session."""

    def __init__(
        self,
        session_id: str,
        version: int = SESSION_FORMAT_VERSION,
        created_at: Optional[int] = None,
        cwd: Optional[str] = None,
        parent_session: Optional[str] = None,
        seed_length: Optional[int] = None,
        origin: Optional[str] = None,
        delegation_depth: Optional[int] = None,
        agent_preset: Optional[str] = None,
    ):
        self.version = version
        self.id = session_id
        self.created_at = created_at if created_at is not None else int(time.time() * 1000)
        self.cwd = cwd
        self.parent_session = parent_session
        self.seed_length = seed_length
        self.origin = origin
        self.delegation_depth = delegation_depth
        self.agent_preset = agent_preset

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "version": self.version,
            "id": self.id,
            "createdAt": self.created_at,
        }
        if self.cwd is not None:
            result["cwd"] = self.cwd
        if self.parent_session is not None:
            result["parentSession"] = self.parent_session
        if self.seed_length is not None:
            result["seedLength"] = self.seed_length
        if self.origin is not None:
            result["origin"] = self.origin
        if self.delegation_depth is not None:
            result["delegationDepth"] = self.delegation_depth
        if self.agent_preset is not None:
            result["agentPreset"] = self.agent_preset
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionHeader":
        return cls(
            session_id=data.get("id", "default-session"),
            version=data.get("version", SESSION_FORMAT_VERSION),
            created_at=data.get("createdAt"),
            cwd=data.get("cwd"),
            parent_session=data.get("parentSession"),
            seed_length=data.get("seedLength"),
            origin=data.get("origin"),
            delegation_depth=data.get("delegationDepth"),
            agent_preset=data.get("agentPreset"),
        )


class Session:
    """
    An event-sourced session: append-only log of SessionEvents and live SessionSurface projection.
    """

    def __init__(
        self,
        session_id: str,
        seed: Optional[List[Dict[str, Any]]] = None,
        header: Optional[SessionHeader] = None,
        ctx: Optional[Any] = None,
    ):
        self.ctx = ctx
        self.header = header or SessionHeader(session_id=session_id)
        self.events: List[Dict[str, Any]] = list(seed or [])
        self.first_live_seq = len(self.events)
        self._surface_manager = SurfaceManager(self.events)

        # Cache state
        self._cached_messages: Optional[List[Dict[str, Any]]] = None
        self._cached_generation: int = -1
        self._cached_nodes_len: int = -1
        self._header_folded_seq: int = -1
        self._cached_request_header: Optional[Dict[str, Any]] = None
        self._context_folded_seq: int = -1
        self._cached_request_context: Optional[Dict[str, Any]] = None

    @property
    def id(self) -> str:
        return self.header.id

    @property
    def session_id(self) -> str:
        return self.header.id

    @property
    def surface(self) -> SurfaceManager:
        return self._surface_manager

    @property
    def seq(self) -> int:
        return len(self.events)

    @classmethod
    def create(
        cls,
        session_id: str,
        seed: Optional[List[Dict[str, Any]]] = None,
        header: Optional[SessionHeader] = None,
        ctx: Optional[Any] = None,
    ) -> "Session":
        return cls(session_id=session_id, seed=seed, header=header, ctx=ctx)

    @classmethod
    def from_restore(
        cls,
        session_id: str,
        seed: List[Dict[str, Any]],
        header: SessionHeader,
        ctx: Optional[Any] = None,
    ) -> "Session":
        session = cls(session_id=session_id, seed=seed, header=header, ctx=ctx)
        return session

    def append(
        self,
        event_type: str,
        data: Dict[str, Any],
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
        ignorable: bool = False,
    ) -> Dict[str, Any]:
        """
        Append one typed event to the log and synchronously notify observers via ctx.emit.
        """
        event_seq = len(self.events)
        event: Dict[str, Any] = {
            "type": event_type,
            "seq": event_seq,
            "time": int(time.time() * 1000),
            "session_id": self.id,
            "data": data,
        }

        if ignorable:
            event["ignorable"] = True

        if is_surface_eligible_type(event_type):
            if surface_op is None:
                surface_op = "append"
            event["surfaceOp"] = surface_op
            if source_event_seqs is not None:
                event["sourceEventSeqs"] = list(source_event_seqs)

        # Validate against surface
        self._surface_manager.validate_next(event)

        # Commit to log
        self.events.append(event)

        # Notify Cordis listeners
        if self.ctx:
            self.ctx.emit("session/event", self, event)

        return event

    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible helper for appending events."""
        surface_op = "append" if is_surface_eligible_type(event_type) else None
        return self.append(event_type, data, surface_op=surface_op)

    def append_user_message(
        self,
        text: str,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"content": text}
        if source:
            data["source"] = source
        return self.append("user/message", data, surface_op=surface_op or "append")

    def append_assistant_message(
        self,
        message: Dict[str, Any],
        turn: Optional[int] = None,
        step: Optional[int] = None,
        usage: Optional[Dict[str, Any]] = None,
        timing: Optional[Dict[str, Any]] = None,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"message": message}
        if turn is not None:
            data["turn"] = turn
        if step is not None:
            data["step"] = step
        if usage is not None:
            data["usage"] = usage
        if timing is not None:
            data["timing"] = timing
        return self.append("assistant/message", data, surface_op=surface_op or "append")

    def append_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: str,
        turn: Optional[int] = None,
        step: Optional[int] = None,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "name": name,
            "result": result,
            "message": {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": result,
            },
        }
        if turn is not None:
            data["turn"] = turn
        if step is not None:
            data["step"] = step
        return self.append(
            "tool/result",
            data,
            surface_op=surface_op or "append",
            source_event_seqs=source_event_seqs,
        )

    def append_request_header(self, header: Dict[str, Any], reason: str = "initial") -> Dict[str, Any]:
        return self.append("request/header", {"header": header, "reason": reason})

    def append_request_context(self, provider: str, model: str, context_window: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"provider": provider, "model": model}
        if context_window is not None:
            payload["contextWindow"] = context_window
        return self.append("request/context", payload)

    def request_header(self) -> Optional[Dict[str, Any]]:
        """Fold and cache the latest request/header from the event log."""
        if self._header_folded_seq < len(self.events) - 1:
            for idx in range(self._header_folded_seq + 1, len(self.events)):
                event = self.events[idx]
                if event.get("type") == "request/header":
                    self._cached_request_header = event.get("data", {}).get("header")
            self._header_folded_seq = len(self.events) - 1
        return self._cached_request_header

    def request_context(self) -> Optional[Dict[str, Any]]:
        """Fold and cache the latest request/context from the event log."""
        if self._context_folded_seq < len(self.events) - 1:
            for idx in range(self._context_folded_seq + 1, len(self.events)):
                event = self.events[idx]
                if event.get("type") == "request/context":
                    self._cached_request_context = event.get("data")
            self._context_folded_seq = len(self.events) - 1
        return self._cached_request_context

    def derive_messages(self, system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Derive messages array for LLM API call by projecting current surface nodes.
        Cached until surface nodes or replace_generation changes.
        """
        nodes = self._surface_manager.nodes
        gen = self._surface_manager.replace_generation

        if (
            self._cached_messages is None
            or self._cached_generation != gen
            or self._cached_nodes_len != len(nodes)
        ):
            surface_messages: List[Dict[str, Any]] = []
            for seq in nodes:
                if seq < len(self.events):
                    msg = derive_event_message(self.events[seq])
                    if msg is not None:
                        surface_messages.append(msg)

            self._cached_messages = surface_messages
            self._cached_generation = gen
            self._cached_nodes_len = len(nodes)

        # Assemble with system prompt if provided
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(self._cached_messages or [])

        return messages

    async def flush(self) -> None:
        """Dispatch durability checkpoint."""
        if self.ctx:
            await self.ctx.parallel("session/flush", self)


class SessionStore:
    """
    In-memory session store mounted at `ctx.sessions`.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._sessions: Dict[str, Session] = {}

    def create(
        self,
        session_id: Optional[str] = None,
        seed: Optional[List[Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Session:
        sid = session_id or f"session-{len(self._sessions) + 1}"
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already exists in store')

        header = SessionHeader.from_dict({"id": sid, **(meta or {})})
        session = Session(session_id=sid, seed=seed, header=header, ctx=self.ctx)
        self._sessions[sid] = session

        if self.ctx:
            self.ctx.emit("session/created", session)

        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def prepare(
        self,
        session_id: Optional[str] = None,
        seed: Optional[List[Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Session:
        sid = session_id or f"session-{len(self._sessions) + 1}"
        header = SessionHeader.from_dict({"id": sid, **(meta or {})})
        return Session(session_id=sid, seed=seed, header=header, ctx=self.ctx)

    def enter(self, session: Session) -> Callable[[], None]:
        sid = session.id
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already in store')
        self._sessions[sid] = session
        session.ctx = self.ctx

        def disposer() -> None:
            self._sessions.pop(sid, None)

        if self.ctx:
            self.ctx.effect(disposer)
            self.ctx.emit("session/created", session)

        return disposer

    async def flush(self, session: Optional[Session] = None) -> None:
        if self.ctx:
            await self.ctx.parallel("session/flush", session)


class SessionService(Session):
    """
    Backward-compatibility wrapper: mounts SessionService as a single-session or session facade.
    """

    def __init__(self, session_id: str = "default-session", ctx: Optional[Any] = None):
        super().__init__(session_id=session_id, ctx=ctx)


class SessionPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session`: In-memory session store & event sourcing.
    """

    id = "session"
    name = "@deepseek-ai/dsh-session"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("sessions"):
            store = SessionStore(ctx)
            ctx.set_service("sessions", store)
