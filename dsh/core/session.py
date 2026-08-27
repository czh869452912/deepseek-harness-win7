"""
Event-Sourced Session Service and Session Store mounted at `ctx.sessions`.
Maintains append-only session log, SurfaceManager projection, and EpochHeader/RequestContext folding.
1:1 aligned with official `@deepseek-ai/dsh-session`.
"""

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin
from dsh.core.surface import (
    SurfaceManager,
    derive_event_message,
    is_surface_eligible_type,
)

SESSION_FORMAT_VERSION = 0
SessionEvent = Dict[str, Any]


class SessionForkError(ValueError):
    """Typed rejection raised by SessionStore.fork (upstream parity)."""
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code
        self.name = "SessionForkError"


def snapshot_json_value(value: Any) -> Any:
    """
    Validate and return a deep snapshot of a JSON-serializable structure.
    Returns None if the value is not losslessly JSON serializable.
    """
    try:
        raw = json.dumps(value, ensure_ascii=False)
        return json.loads(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def canonical_header(header: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a canonical, sorted dictionary snapshot of an EpochHeader.
    """
    snapshot = snapshot_json_value(header) or {}
    if not isinstance(snapshot, dict):
        return {}
    res: Dict[str, Any] = {}
    if "config" in snapshot:
        res["config"] = snapshot["config"]
    if "adapterDefaults" in snapshot:
        res["adapterDefaults"] = snapshot["adapterDefaults"]
    if "system" in snapshot and snapshot["system"]:
        res["system"] = snapshot["system"]
    if "tools" in snapshot and snapshot["tools"]:
        res["tools"] = snapshot["tools"]
    return res


def header_equals(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """
    Compare two EpochHeader dicts for canonical equality.
    """
    ca = canonical_header(a)
    cb = canonical_header(b)
    return json.dumps(ca, sort_keys=True, ensure_ascii=False) == json.dumps(cb, sort_keys=True, ensure_ascii=False)


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
        if version != SESSION_FORMAT_VERSION:
            raise ValueError("session header version must be %s, got %s" % (SESSION_FORMAT_VERSION, version))
        self.version = version
        self.id = session_id
        self.created_at = created_at if created_at is not None else int(time.time() * 1000)
        self.cwd = cwd
        self.parent_session = parent_session
        self.seed_length = seed_length
        self.origin = origin
        self.delegation_depth = delegation_depth
        self.agent_preset = agent_preset
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("session id must be a non-empty string")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, int) or self.created_at < 0:
            raise ValueError("session header createdAt must be a non-negative safe integer")
        if self.cwd is not None and not os.path.isabs(self.cwd):
            raise ValueError("session cwd must be an absolute path")
        if self.parent_session is not None and not isinstance(self.parent_session, str):
            raise ValueError("session header parentSession must be a string")
        if self.seed_length is not None and (isinstance(self.seed_length, bool) or not isinstance(self.seed_length, int) or self.seed_length < 0):
            raise ValueError("session header seedLength must be a non-negative safe integer")
        if self.origin is not None and self.origin != "subagent":
            raise ValueError('session header origin must be "subagent"')
        if self.delegation_depth is not None and (isinstance(self.delegation_depth, bool) or not isinstance(self.delegation_depth, int) or self.delegation_depth < 0):
            raise ValueError("session header delegationDepth must be a non-negative safe integer")
        if self.agent_preset is not None and not isinstance(self.agent_preset, str):
            raise ValueError("session header agentPreset must be a string")

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


class SessionPreparation:
    """Staged session preparation helper."""

    def __init__(self, session: "Session", disposer: Optional[Callable[[], None]] = None):
        self.session = session
        self._disposer = disposer
        self._released = False

    @classmethod
    def create(cls, session: "Session", release: Optional[Callable[[], None]] = None) -> "SessionPreparation":
        return cls(session, release)

    def dispose(self) -> None:
        if not self._released and self._disposer:
            self._released = True
            self._disposer()


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
        self._attached = False
        self._appending = False
        self.header = header or SessionHeader(session_id=session_id)
        self.events: List[Dict[str, Any]] = []

        self._surface_manager = SurfaceManager(self.events)

        if seed is not None:
            for index, ev in enumerate(seed):
                snapshot = snapshot_json_value(ev)
                self._validate_seed_event(snapshot, index)
                self._surface_manager.validate_next(snapshot)
                self.events.append(snapshot)

        self.first_live_seq = len(self.events)

        if seed is not None and (len(self.events) == 0 or self.events[-1].get("type") != "session/end-seed"):
            self.append("session/end-seed", {}, ignorable=True)

        self._cached_messages: Optional[List[Dict[str, Any]]] = None
        self._cached_generation: int = -1
        self._cached_nodes_len: int = -1
        self._header_folded_seq: int = -1
        self._cached_request_header: Optional[Dict[str, Any]] = None
        self._context_folded_seq: int = -1
        self._cached_request_context: Optional[Dict[str, Any]] = None

    @staticmethod
    def _validate_seed_event(event: Any, index: int) -> None:
        if not isinstance(event, dict):
            raise ValueError("seed event at index %s is not a plain JSON record" % index)
        allowed = {"type", "seq", "time", "data", "surfaceOp", "sourceEventSeqs", "ignorable"}
        extra = set(event.keys()) - allowed
        if extra:
            raise ValueError("seed event at index %s has an invalid event envelope" % index)
        if event.get("type") == "request/header-delta":
            raise ValueError("seed event at index %s uses unsupported legacy request/header-delta format" % index)
        if not isinstance(event.get("type"), str) or not event.get("type"):
            raise ValueError("seed event at index %s has an invalid type" % index)
        seq = event.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise ValueError("seed event at index %s has an invalid seq" % index)
        stamp = event.get("time")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
            raise ValueError("seed event at index %s has an invalid time" % index)
        if "data" not in event:
            raise ValueError("seed event at index %s is missing data" % index)
        if event.get("ignorable") not in (None, True):
            raise ValueError("seed event at index %s has invalid ignorable marker" % index)
        if event.get("type") == "request/header":
            data = event.get("data")
            header = data.get("header") if isinstance(data, dict) else None
            config = header.get("config") if isinstance(header, dict) else None
            if not isinstance(config, dict) or not isinstance(config.get("provider"), str) or not config.get("provider") or not isinstance(config.get("model"), str) or not config.get("model"):
                raise ValueError("seed request/header at index %s lacks provider/model" % index)

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
        from dsh.session.repair import interrupted_turn_closers
        repaired_seed = list(seed)
        closers = interrupted_turn_closers(repaired_seed)
        repaired_seed.extend(closers)
        session = cls(session_id=session_id, seed=repaired_seed, header=header, ctx=ctx)
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
        if self._appending:
            raise RuntimeError("session append cannot reenter while another append is being published")

        data_snapshot = snapshot_json_value(data)
        if data_snapshot is None and data is not None:
            raise TypeError("session event data is not losslessly JSON-serializable")
        event_seq = len(self.events)
        event: Dict[str, Any] = {
            "type": event_type,
            "seq": event_seq,
            "time": int(time.time() * 1000),
            "data": data_snapshot,
        }

        if ignorable:
            event["ignorable"] = True

        if is_surface_eligible_type(event_type):
            if surface_op is None:
                surface_op = "append"
            event["surfaceOp"] = surface_op
            if source_event_seqs is not None:
                event["sourceEventSeqs"] = list(source_event_seqs)

        self._surface_manager.validate_next(event)

        self._appending = True
        try:
            self.events.append(event)

            if self.ctx and self._attached:
                try:
                    self.ctx.emit("session/event", self, event)
                except Exception as e:
                    logger = getattr(self.ctx, "logger", None)
                    if logger and hasattr(logger, "warn"):
                        logger.warn(f'session "{self.id}": session/event listener threw: {e}')
            return event
        finally:
            self._appending = False

    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        surface_op = "append" if is_surface_eligible_type(event_type) else None
        return self.append(event_type, data, surface_op=surface_op)

    def append_user_message(
        self,
        text: str,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        msg_id = f"user-{os.urandom(4).hex()}"
        src = source if (isinstance(source, dict) and "kind" in source) else {"kind": "user"}
        data: Dict[str, Any] = {
            "id": msg_id,
            "content": text,
            "source": src,
        }
        return self.append("user/message", data, surface_op=surface_op or "append")

    def append_assistant_message(
        self,
        message: Dict[str, Any],
        turn: Optional[int] = None,
        step: Optional[int] = None,
        usage: Optional[Dict[str, Any]] = None,
        timing: Optional[Dict[str, Any]] = None,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
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
        return self.append(
            "assistant/message",
            data,
            surface_op=surface_op or "append",
            source_event_seqs=source_event_seqs,
        )

    def append_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: str,
        turn: Optional[int] = None,
        step: Optional[int] = None,
        timing: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
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
        if timing is not None:
            data["timing"] = timing
        if error is not None:
            data["error"] = error
        if meta is not None:
            data["meta"] = meta
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
        self._counter = 0
        self._attachments: Dict[str, Dict[str, Any]] = {}

    def create(
        self,
        session_id: Optional[str] = None,
        seed: Optional[List[Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Session:
        if session_id is None:
            self._counter += 1
            sid = f"session-{self._counter}"
            while sid in self._sessions:
                self._counter += 1
                sid = f"session-{self._counter}"
        else:
            sid = session_id
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already exists')
        session = self.prepare(sid, {"seed": seed, "meta": meta} if seed is not None or meta is not None else None)
        disposer = self.enter(session)
        try:
            self.announce(session)
        except Exception:
            disposer()
            raise
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def prepare(self, session_id: Optional[str] = None, options: Optional[Dict[str, Any]] = None,
                seed: Optional[List[Dict[str, Any]]] = None,
                meta: Optional[Dict[str, Any]] = None) -> Session:
        options = dict(options or {})
        if seed is not None:
            options["seed"] = seed
        if meta is not None:
            options["meta"] = meta
        seed = options.get("seed")
        meta = options.get("meta") or {}
        if session_id is None:
            self._counter += 1
            session_id = f"session-{self._counter}"
            while session_id in self._sessions:
                self._counter += 1
                session_id = f"session-{self._counter}"
        if session_id in self._sessions:
            raise ValueError(f'session "{session_id}" already exists')
        header = SessionHeader.from_dict({"id": session_id, **meta})
        if options.get("seedSource") == "persistence":
            return Session.from_restore(session_id, list(seed or []), header, ctx=self.ctx)
        return Session.create(session_id, seed=seed, header=header, ctx=self.ctx)

    def enter(self, session: Session) -> Callable[[], None]:
        sid = session.id
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already in store')
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already exists')
        self._sessions[sid] = session
        session.ctx = self.ctx
        session._attached = True
        state = {"session": session, "announced": False, "detached": False}
        self._attachments[sid] = state

        def disposer() -> None:
            if state["detached"]:
                return
            state["detached"] = True
            if self._sessions.get(sid) is session:
                self._sessions.pop(sid, None)
                self._attachments.pop(sid, None)
                if state["announced"] and self.ctx:
                    try:
                        self.ctx.emit("session/disposed", session)
                    except Exception:
                        pass

        return disposer

    def announce(self, session: Session) -> None:
        state = self._attachments.get(session.id)
        if state is None or self._sessions.get(session.id) is not session:
            raise ValueError(f'session "{session.id}" is not live in this store')
        if state["announced"]:
            raise ValueError(f'session "{session.id}" was already announced')
        state["announced"] = True
        if self.ctx:
            self.ctx.emit("session/created", session)

    def _live(self, session: Session) -> Dict[str, Any]:
        state = self._attachments.get(session.id)
        if state is None or self._sessions.get(session.id) is not session:
            raise ValueError(f'session "{session.id}" is not live in this store')
        return state

    async def flush(self, session: Optional[Session] = None) -> bool:
        if session is not None:
            self._live(session)
        if self.ctx:
            listeners = self.ctx.events._dispatch_hooks("emit", "session/flush", self.ctx, [session])
            await self.ctx.parallel("session/flush", session)
            return bool(listeners)
        return False

    def list(self) -> List[Session]:
        return list(self._sessions.values())

    def fork(self, source: Union[Session, str], boundary: Optional[int] = None, child_session_id: Optional[str] = None) -> Session:
        if child_session_id is not None and child_session_id in self._sessions:
            raise SessionForkError(f'session "{child_session_id}" already exists', "SESSION_ALREADY_EXISTS")
        if isinstance(source, str):
            live = self.get(source)
            if live is None:
                raise SessionForkError(f'session "{source}" not found', "SESSION_NOT_FOUND")
        else:
            live = self.get(source.id)
            if live is None:
                raise SessionForkError(f'session "{source.id}" not found', "SESSION_NOT_FOUND")
            if live is not source:
                raise SessionForkError(f'session "{source.id}" is not the live store instance', "SESSION_NOT_LIVE")
        events = live.events
        if boundary is None:
            if not events:
                seed = []
                meta = {"parentSession": live.id, "seedLength": 0}
                if live.header.cwd is not None:
                    meta["cwd"] = live.header.cwd
                return self.create(child_session_id, seed=seed, meta=meta)
            boundary = events[-1]["seq"]
        if not isinstance(boundary, int) or boundary < 0 or boundary >= len(events) or events[boundary].get("seq") != boundary:
            raise SessionForkError(f'fork boundary {boundary} does not exist in session "{live.id}"', "INVALID_BOUNDARY")
        last_turn = None
        for ev in events[:boundary + 1]:
            if ev.get("type") in ("turn/start", "turn/end"):
                last_turn = ev
        if last_turn and last_turn.get("type") == "turn/start":
            turn = last_turn.get("data", {}).get("turn")
            raise SessionForkError(f'fork boundary {boundary} in session "{live.id}" ends inside open turn {turn}', "OPEN_TURN")
        seed = [snapshot_json_value(ev) for ev in events[:boundary + 1]]
        meta = {"parentSession": live.id, "seedLength": len(seed)}
        if live.header.cwd is not None:
            meta["cwd"] = live.header.cwd
        return self.create(child_session_id, seed=seed, meta=meta)


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
