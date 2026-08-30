"""
Event-Sourced Session Service and Session Store mounted at `ctx.sessions`.
Maintains append-only session log, SurfaceManager projection, and EpochHeader/RequestContext folding.
1:1 aligned with official `@deepseek-ai/dsh-session`.
"""

import json
import os
import time
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Union
from dsh.cordis.plugin import Plugin
from dsh.core.surface import (
    SurfaceManager,
    derive_event_message,
    is_surface_eligible_type,
    tool_pairing_balanced_after,
)

SESSION_FORMAT_VERSION = 0
SessionEvent = Dict[str, Any]

KNOWN_SESSION_EVENT_TYPES: FrozenSet[str] = frozenset([
    "agent-preset/selected",
    "agent/inbox/spliced",
    "approval/asked",
    "approval/decided",
    "approval/policy",
    "assistant/chunk",
    "assistant/message",
    "command/done",
    "command/run",
    "compaction/end",
    "compaction/prune",
    "compaction/start",
    "compaction/summary",
    "feedback/record",
    "goal/change",
    "hook/invoked",
    "hook/result",
    "llm/retry",
    "llm/retry-started",
    "model/selection",
    "permission/preset",
    "plan/mode",
    "request/context",
    "request/header",
    "sandbox/mode",
    "schedule/change",
    "session-log-deepseek/delivery-accepted",
    "session/end-seed",
    "session/title",
    "session/title-llm-request",
    "step/end",
    "step/start",
    "subagent/descriptor",
    "subagent/model-selection-policy",
    "team/member",
    "team/message/delivered",
    "team/message/queued",
    "team/task",
    "todo/write",
    "tool-workflow/agent-end",
    "tool-workflow/agent-start",
    "tool-workflow/run-end",
    "tool-workflow/run-start",
    "tool/call",
    "tool/code-dispatch",
    "tool/code-dispatch-start",
    "tool/result",
    "turn/end",
    "turn/start",
    "user/message",
    "web/deepseek-search-llm-request",
])


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
    if "adapterDefaults" in snapshot and snapshot["adapterDefaults"]:
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


def fold_request_header(events: List[Dict[str, Any]], from_header: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Fold header events into the latest canonical header."""
    state = from_header
    for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "request/header":
            hdr = ev.get("data", {}).get("header")
            if isinstance(hdr, dict):
                state = canonical_header(hdr)
    return state


class SessionForkError(ValueError):
    """Structured error thrown by SessionStore.fork."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


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
        sid = str(data.get("id", "default-session"))
        return validate_session_header(sid, data)


def validate_session_header(session_id: str, input_data: Any) -> SessionHeader:
    """Validate plain dictionary session header against schema rules."""
    if not isinstance(input_data, dict):
        raise ValueError("session header is not a plain JSON record")
    version = input_data.get("version", SESSION_FORMAT_VERSION)
    if version != SESSION_FORMAT_VERSION:
        raise ValueError(f"session header version must be {SESSION_FORMAT_VERSION}, got {version}")
    hid = input_data.get("id", session_id)
    if hid != session_id:
        raise ValueError(f'session header id "{hid}" does not match session id "{session_id}"')

    raw_created = input_data.get("createdAt")
    if raw_created is None:
        raw_created = input_data.get("created_at")
    created_at = int(raw_created) if raw_created is not None else int(time.time() * 1000)
    if created_at < 0:
        raise ValueError("session header createdAt must be a non-negative safe integer")

    cwd = input_data.get("cwd")
    if cwd is not None:
        if not isinstance(cwd, str):
            raise ValueError("session header cwd must be a string")
        if not os.path.isabs(cwd):
            raise ValueError(f'session header cwd must be an absolute path, got "{cwd}"')

    parent_session = input_data.get("parentSession") or input_data.get("parent_session")
    if parent_session is not None and not isinstance(parent_session, str):
        raise ValueError("session header parentSession must be a string")

    raw_seed_len = input_data.get("seedLength")
    if raw_seed_len is None:
        raw_seed_len = input_data.get("seed_length")
    seed_length = int(raw_seed_len) if raw_seed_len is not None else None
    if seed_length is not None and seed_length < 0:
        raise ValueError("session header seedLength must be a non-negative safe integer")

    origin = input_data.get("origin")
    if origin is not None and origin != "subagent":
        raise ValueError('session header origin must be "subagent"')

    raw_depth = input_data.get("delegationDepth")
    if raw_depth is None:
        raw_depth = input_data.get("delegation_depth")
    delegation_depth = int(raw_depth) if raw_depth is not None else None
    if delegation_depth is not None and delegation_depth < 0:
        raise ValueError("session header delegationDepth must be a non-negative safe integer")

    agent_preset = input_data.get("agentPreset") or input_data.get("agent_preset")
    if agent_preset is not None and not isinstance(agent_preset, str):
        raise ValueError("session header agentPreset must be a string")

    return SessionHeader(
        session_id=session_id,
        version=version,
        created_at=created_at,
        cwd=cwd,
        parent_session=parent_session,
        seed_length=seed_length,
        origin=origin,
        delegation_depth=delegation_depth,
        agent_preset=agent_preset,
    )


class SessionPreparation:
    """Staged session preparation helper."""

    def __init__(self, session: "Session", disposer: Optional[Callable[[], None]] = None):
        self.session = session
        self._disposer = disposer

    def dispose(self) -> None:
        if self._disposer:
            self._disposer()


class Session:
    """
    An event-sourced session: append-only log of SessionEvents and live SessionSurface projection.
    1:1 aligned with official `@deepseek-ai/dsh-session`.
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
        self.events: List[Dict[str, Any]] = []

        self._surface_manager = SurfaceManager(self.events)

        if seed is not None:
            for ev in seed:
                if isinstance(ev, dict) and ev.get("type") == "request/header-delta":
                    raise ValueError("unsupported legacy request/header-delta")
                snapshot = snapshot_json_value(ev)
                self._surface_manager.validate_next(snapshot)
                self.events.append(snapshot)

        self._appending = False

        # Incremental derived messages cache: O(ΔN) projection
        self._derived: List[Dict[str, Any]] = []
        self._derived_nodes: int = 0
        self._derived_generation: int = 0

        self._header_folded_seq: int = -1
        self._cached_request_header: Optional[Dict[str, Any]] = None
        self._context_folded_seq: int = -1
        self._cached_request_context: Optional[Dict[str, Any]] = None

        self._first_live_seq = len(self.events)

        if seed is not None and (len(self.events) == 0 or self.events[-1].get("type") != "session/end-seed"):
            self.append("session/end-seed", {})

    @property
    def first_live_seq(self) -> int:
        return self._first_live_seq

    @property
    def firstLiveSeq(self) -> int:
        return self._first_live_seq

    @property
    def id(self) -> str:
        return self.header.id

    @property
    def session_id(self) -> str:
        return self.header.id

    @property
    def parent_session_id(self) -> Optional[str]:
        return getattr(self.header, "parent_session", None)

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
        Strict 1:1 SessionEvent envelope: { type, seq, time, data, surfaceOp?, sourceEventSeqs? }.
        """
        if event_type == "request/header-delta":
            raise ValueError("unsupported legacy request/header-delta")

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
            "data": data_snapshot if data_snapshot is not None else {},
        }

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

            if self.ctx:
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
        message_id: Optional[str] = None,
        source_event_seqs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        msg_id = message_id or f"user-{os.urandom(4).hex()}"
        src = source if (isinstance(source, dict) and "kind" in source) else {"kind": "user"}
        data: Dict[str, Any] = {
            "role": "user",
            "id": msg_id,
            "content": text,
            "source": src,
        }
        return self.append(
            "user/message",
            data,
            surface_op=surface_op or "append",
            source_event_seqs=source_event_seqs,
        )

    def append_assistant_message(
        self,
        message: Dict[str, Any],
        turn: Optional[int] = None,
        step: Optional[int] = None,
        usage: Optional[Dict[str, Any]] = None,
        timing: Optional[Dict[str, Any]] = None,
        interrupted: bool = False,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "turn": turn if turn is not None else 1,
            "step": step if step is not None else 1,
            "message": message,
        }
        if usage is not None:
            data["usage"] = usage
        if timing is not None:
            data["timing"] = timing
        if interrupted:
            data["interrupted"] = True
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
        tool_msg = {
            "role": "user",
            "content": [
                {
                    "type": "tool-result",
                    "toolCallId": tool_call_id,
                    "content": [{"type": "text", "text": result}],
                    "isError": error is not None,
                }
            ],
            "source": {
                "kind": "tool",
                "callId": tool_call_id,
            },
        }
        data: Dict[str, Any] = {
            "turn": turn if turn is not None else 1,
            "step": step if step is not None else 1,
            "message": tool_msg,
        }
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

    def append_request_header(
        self,
        header: Dict[str, Any],
        reason: str = "initial",
        starts_series: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"header": header, "reason": reason}
        if starts_series:
            payload["startsSeries"] = True
        return self.append("request/header", payload)

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
                    hdr = event.get("data", {}).get("header")
                    if isinstance(hdr, dict):
                        self._cached_request_header = canonical_header(hdr)
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
        Cached incrementally: O(ΔN) projection over unseen surface nodes.
        Rebuilds only on surface rewrite (replace_generation change).
        """
        nodes = self._surface_manager.nodes
        gen = self._surface_manager.replace_generation

        if gen != self._derived_generation:
            self._derived = []
            self._derived_nodes = 0
            self._derived_generation = gen

        for seq in nodes[self._derived_nodes:]:
            if 0 <= seq < len(self.events):
                msg = self.derive_event_message(self.events[seq])
                if msg is not None:
                    self._derived.append(msg)

        self._derived_nodes = len(nodes)

        surface_history = list(self._derived)
        if system_prompt is not None:
            return [{"role": "system", "content": system_prompt}] + surface_history
        return surface_history

    def deriveMessages(self, system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        """CamelCase alias 1:1 with reference."""
        return self.derive_messages(system_prompt=system_prompt)

    def derive_event_message(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Instance face of pure per-node derive_event_message."""
        return derive_event_message(event)

    def fork(
        self,
        child_session_id: str,
        boundary: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "Session":
        """
        Fork a child session from a balanced completed-turn prefix of this session.
        1:1 aligned with reference forkSession.
        """
        cut = boundary if boundary is not None else len(self.events)
        if cut < 0 or cut > len(self.events):
            raise ValueError(f"fork boundary {cut} out of bounds (0..{len(self.events)})")

        nodes = self.surface.nodes
        surface_nodes_in_cut = [s for s in nodes if s < cut]
        if surface_nodes_in_cut:
            if not tool_pairing_balanced_after(self.events[:cut], surface_nodes_in_cut, surface_nodes_in_cut[-1]):
                raise ValueError("fork boundary is not tool-pairing balanced")

        seed_events = [snapshot_json_value(ev) for ev in self.events[:cut]]
        meta_dict = dict(meta or {})
        meta_dict["parentSession"] = self.id
        meta_dict["seedLength"] = cut
        meta_dict["delegationDepth"] = (getattr(self.header, "delegation_depth", 0) or 0) + 1

        header = validate_session_header(child_session_id, {"id": child_session_id, **meta_dict})
        child = Session(session_id=child_session_id, seed=seed_events, header=header, ctx=self.ctx)
        return child

    async def flush(self) -> bool:
        """Dispatch durability checkpoint."""
        if self.ctx:
            sessions_svc = self.ctx.get("sessions")
            if sessions_svc and hasattr(sessions_svc, "flush"):
                return await sessions_svc.flush(self)
            res = await self.ctx.parallel("session/flush", self)
            return len(res) > 0 if isinstance(res, list) else True
        return False


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
        parent_session_id: Optional[str] = None,
    ) -> Session:
        sid = session_id or f"session-{len(self._sessions) + 1}"
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already exists in store')

        meta_dict = dict(meta or {})
        if parent_session_id is not None:
            meta_dict["parentSession"] = parent_session_id

        header = validate_session_header(sid, {"id": sid, **meta_dict})
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
        parent_session_id: Optional[str] = None,
        seed_source: Optional[str] = None,
        seedSource: Optional[str] = None,
    ) -> SessionPreparation:
        sid = session_id or f"session-{len(self._sessions) + 1}"
        source_mode = seed_source or seedSource
        if source_mode == "persistence":
            hdr = meta if isinstance(meta, SessionHeader) else validate_session_header(sid, dict(meta or {}))
            session = Session.from_restore(session_id=sid, seed=seed or [], header=hdr, ctx=self.ctx)
            return SessionPreparation(session=session)

        meta_dict = dict(meta or {})
        if parent_session_id is not None:
            meta_dict["parentSession"] = parent_session_id
        header = validate_session_header(sid, {"id": sid, **meta_dict})
        session = Session(session_id=sid, seed=seed, header=header, ctx=self.ctx)
        return SessionPreparation(session=session)

    def enter(self, session: Session) -> Callable[[], None]:
        sid = session.id
        if sid in self._sessions:
            raise ValueError(f'session "{sid}" already in store')
        self._sessions[sid] = session
        session.ctx = self.ctx

        def disposer() -> None:
            self._sessions.pop(sid, None)
            if self.ctx:
                self.ctx.emit("session/disposed", session)

        if self.ctx:
            self.ctx.effect(disposer)
            self.ctx.emit("session/created", session)

        return disposer

    def fork(
        self,
        source: Union[str, Session],
        boundary: Optional[Union[int, float]] = None,
        child_session_id: Optional[str] = None,
    ) -> Session:
        if child_session_id is not None and self.get(child_session_id) is not None:
            raise SessionForkError(f'session "{child_session_id}" already exists', 'SESSION_ALREADY_EXISTS')

        live_source = self._resolve_fork_source(source)
        seed = self._fork_seed(live_source, boundary)
        meta_dict: Dict[str, Any] = {
            "parentSession": live_source.id,
            "seedLength": len(seed),
        }
        if live_source.header.cwd is not None:
            meta_dict["cwd"] = live_source.header.cwd

        return self.create(child_session_id, seed=seed, meta=meta_dict)

    def _resolve_fork_source(self, source: Union[str, Session]) -> Session:
        if isinstance(source, str):
            session = self.get(source)
            if session is None:
                raise SessionForkError(f'session "{source}" not found', 'SESSION_NOT_FOUND')
            return session

        live = self.get(source.id)
        if live is None:
            raise SessionForkError(f'session "{source.id}" not found', 'SESSION_NOT_FOUND')
        if live is not source:
            raise SessionForkError(f'session "{source.id}" is not the live store instance', 'SESSION_NOT_LIVE')
        return source

    def _fork_seed(self, session: Session, requested_boundary: Optional[Union[int, float]]) -> List[Dict[str, Any]]:
        events = session.events
        last_event = events[-1] if events else None

        if requested_boundary is not None:
            boundary = requested_boundary
        else:
            if last_event is None:
                return []
            boundary = last_event.get("seq", len(events) - 1)

        if not isinstance(boundary, int) or isinstance(boundary, bool) or boundary < 0 or boundary > 9007199254740991:
            raise SessionForkError(
                f'fork boundary for session "{session.id}" must be a non-negative safe integer, got {boundary}',
                'INVALID_BOUNDARY',
            )

        if boundary >= len(events):
            last_seq = events[-1].get("seq") if events else None
            raise SessionForkError(
                f'fork boundary {boundary} does not exist in session "{session.id}" (last seq: {last_seq if last_seq is not None else "none"})',
                'INVALID_BOUNDARY',
            )

        boundary_event = events[boundary]
        if boundary_event is None or boundary_event.get("seq") != boundary:
            raise SessionForkError(
                f'fork boundary {boundary} does not match a contiguous event seq in session "{session.id}"',
                'INVALID_BOUNDARY',
            )

        prefix = events[: boundary + 1]
        last_turn_boundary = None
        for ev in reversed(prefix):
            if ev.get("type") in ("turn/start", "turn/end"):
                last_turn_boundary = ev
                break

        if last_turn_boundary is not None and last_turn_boundary.get("type") == "turn/start":
            open_turn = last_turn_boundary.get("data", {}).get("turn", 1)
            raise SessionForkError(
                f'fork boundary {boundary} in session "{session.id}" ends inside open turn {open_turn}',
                'OPEN_TURN',
            )

        return [snapshot_json_value(ev) for ev in prefix]

    async def flush(self, session: Optional[Session] = None) -> bool:
        if not self.ctx:
            return False
        import inspect
        events_bus = getattr(self.ctx, "events", None)
        if events_bus and hasattr(events_bus, "_dispatch_hooks"):
            listeners = events_bus._dispatch_hooks("parallel", "session/flush", [session], self.ctx)
            if not listeners:
                return False

            async def _run(cb: Callable[..., Any]) -> Any:
                res = cb(session)
                if inspect.isawaitable(res):
                    return await res
                return res

            import asyncio
            results = await asyncio.gather(*[_run(cb) for cb in listeners], return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    raise r
            return len(listeners) > 0
        else:
            res = await self.ctx.parallel("session/flush", session)
            return len(res) > 0 if isinstance(res, list) else True


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
