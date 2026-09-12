"""
Event-Sourced Session Service and Session Store mounted at `ctx.sessions`.
Ported 1:1 from reference packages/core/session/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import os
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.core.scope import scope_of, scope_target
from dsh.core.session.json import (
    UNDEFINED,
    FrozenList,
    deep_freeze,
    freeze_restored_object,
    snapshot_json_value,
    walk_json_value,
)
from dsh.core.session.preparation import SessionPreparation
from dsh.core.session.request_header import canonical_header, fold_request_header
from dsh.core.session.surface import (
    SurfaceManager,
    derive_event_message,
    is_surface_eligible_type,
    tool_pairing_balanced_after,
)
from dsh.core.session.types import (
    SESSION_FORMAT_VERSION,
    SessionForkError,
    SessionHeader,
    SessionId,
    adopt_session_event,
    assert_current_llm_shape,
    assert_message_event_shape,
    assert_session_event_envelope,
    assert_supported_request_header,
    snapshot_session_event,
    snapshot_session_header,
    validate_restored_session_header,
    validate_session_header,
)
from dsh.typert.protocol import TypertLookupProvider


class _SessionStoreEntry:
    def __init__(self, session_id: str, session: "Session", carrier: Any, emit_ctx: Any):
        self.id = session_id
        self.session = session
        self.carrier = carrier
        self.emit_ctx = emit_ctx
        self.announced = False
        self.announcing = False
        self.appending = False
        self.detach_requested = False

    def detach(self) -> None:
        pass


_attachments: Dict[int, _SessionStoreEntry] = {}


def _collect_session_callbacks(ctx: Any, args: Sequence[Any]) -> List[Callable[..., Any]]:
    if ctx is None:
        return []
    events_bus = getattr(ctx, "events", None)
    if events_bus is not None and hasattr(events_bus, "dispatch"):
        return list(events_bus.dispatch("emit", args))
    return []


def _invoke_contained_session_observers(
    ctx: Any,
    name: str,
    session_id: str,
    args: Sequence[Any],
    callbacks: Sequence[Callable[..., Any]],
) -> None:
    for cb in callbacks:
        try:
            res = cb(*args)
            if hasattr(res, "__await__"):
                import asyncio
                # Async listener rejection containment
                async def _watch(coro: Any) -> None:
                    try:
                        await coro
                    except Exception as err:
                        if ctx and hasattr(ctx, "logger"):
                            ctx.logger.warn(f'session "{session_id}": {name} listener rejected: {err}')
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(_watch(res))
                except Exception:
                    pass
        except Exception as err:
            if ctx and hasattr(ctx, "logger"):
                ctx.logger.warn(f'session "{session_id}": {name} listener threw: {err}')


class Session:
    """
    An event-sourced session: an append-only log of SessionEvents.
    1:1 aligned with reference `Session`.
    """

    def __init__(
        self,
        session_id: str,
        seed: Optional[Sequence[Dict[str, Any]]] = None,
        header: Any = UNDEFINED,
        mode: str = "snapshot",
        ctx: Optional[Any] = None,
    ):
        self.ctx = ctx
        restored_header = (
            validate_restored_session_header(session_id, header)
            if mode == "restore"
            else None
        )

        self._log: List[Dict[str, Any]] = []
        self.log = self._log
        self._surface_manager = SurfaceManager(self._log)
        self._events_snapshot: Optional[List[Dict[str, Any]]] = None

        if seed is not None:
            for index, source in enumerate(seed):
                # The seed is a persistence/replay boundary: validate and detach
                # the complete event in one lossless-JSON pass. The detach
                # sentinel is `undefined` (not `None`) because a JSON `null`
                # seed still reaches the envelope check below, exactly like the
                # reference `snapshotJsonValue(source) === undefined` test.
                snapshot = (
                    source
                    if mode == "restore"
                    else walk_json_value(source, detach=True, undefined_sentinel=UNDEFINED)
                )
                if snapshot is UNDEFINED:
                    raise ValueError(f"seed event at index {index} is not losslessly JSON-serializable")
                assert_session_event_envelope(snapshot, index=index)
                assert_current_llm_shape(snapshot, index=index)
                assert_supported_request_header(
                    snapshot.get("type", ""),
                    snapshot.get("data"),
                    location=f"seed event at index {index}",
                )
                if snapshot.get("seq") != index:
                    raise ValueError(
                        f"seed event at index {index} has seq {snapshot.get('seq')} (expected {index}); seed must be contiguous from 0"
                    )
                try:
                    self._surface_manager.validate_next(snapshot)
                except Exception as error:
                    raise ValueError(f"invalid seed event at index {index}: {error}") from error
                # A restored seed transfers ownership and is frozen iteratively
                # (`freezeRestoredObject`); a borrowed seed became a fresh
                # snapshot above and is deeply frozen (`deepFreeze`).
                self._log.append(
                    freeze_restored_object(snapshot) if mode == "restore" else deep_freeze(snapshot)
                )

        self._first_live_seq = len(self._log)
        if restored_header is not None:
            self.header = restored_header
        else:
            self.header = snapshot_session_header(session_id, header)

        # Append end-seed marker if seed is non-empty or explicitly provided
        if seed is not None and (len(self._log) == 0 or self._log[-1].get("type") != "session/end-seed"):
            self.append("session/end-seed", {})

        # Incremental derived messages cache
        self._derived: List[Dict[str, Any]] = []
        self._derived_nodes: int = 0
        self._derived_generation: int = 0

        # Cached header and context folds
        self._header_fold: Optional[Dict[str, Any]] = None
        self._header_fold_seq: int = 0
        self._context_fold: Optional[Dict[str, Any]] = None
        self._context_fold_seq: int = 0

    @property
    def id(self) -> str:
        return self.header.id

    @property
    def session_id(self) -> str:
        return self.header.id

    @property
    def parent_session_id(self) -> Optional[str]:
        return self.header.parent_session

    @property
    def parentSession(self) -> Optional[str]:
        return self.header.parent_session

    @property
    def surface(self) -> SurfaceManager:
        return self._surface_manager

    @property
    def first_live_seq(self) -> int:
        return self._first_live_seq

    @property
    def firstLiveSeq(self) -> int:
        return self._first_live_seq

    @property
    def seq(self) -> int:
        return len(self._log)

    @property
    def events(self) -> List[Dict[str, Any]]:
        """
        An immutable snapshot of the append-only event log, cached until the
        next append (a previously returned array does not grow later). Events
        and their nested data are deep-frozen at acceptance, so neither a cast
        nor ordinary Python can rewrite durable history.
        """
        if self._events_snapshot is None:
            self._events_snapshot = FrozenList(self._log)
        return self._events_snapshot

    @classmethod
    def create(
        cls,
        session_id: str,
        seed: Optional[Sequence[Dict[str, Any]]] = None,
        header: Any = UNDEFINED,
        ctx: Optional[Any] = None,
    ) -> "Session":
        return cls(session_id=session_id, seed=seed, header=header, mode="snapshot", ctx=ctx)

    @classmethod
    def from_restore(
        cls,
        session_id: str,
        seed: Sequence[Dict[str, Any]],
        header: Union[SessionHeader, Dict[str, Any]],
        ctx: Optional[Any] = None,
    ) -> "Session":
        # Exactly `new Session(id, seed, header, 'restore')` (index.ts:493-494):
        # a restore takes ownership of the supplied values as they are. It does
        # NOT migrate legacy events and does NOT synthesize interrupted-turn
        # closers - that repair belongs to the persistence layer, which performs
        # it before handing the seed over.
        return cls(session_id=session_id, seed=seed, header=header, mode="restore", ctx=ctx)

    fromRestore = from_restore

    def append(
        self,
        event_type: str,
        data: Dict[str, Any],
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Append one typed event to the log and synchronously notify observers.
        1:1 aligned with reference `Session.append`.
        """
        # Surface options can come in as surface_op/source_event_seqs or kwargs / opts dict
        s_op = surface_op
        s_seqs = source_event_seqs
        opts = kwargs.get("opts")
        if isinstance(opts, dict):
            if s_op is None:
                s_op = opts.get("surfaceOp")
            if s_seqs is None:
                s_seqs = opts.get("sourceEventSeqs")

        # No marker is synthesized here: the TS overloads reject a
        # surface-eligible append without one at COMPILE time, so the runtime
        # guard in the surface validator is the only remaining enforcement and
        # must observe the missing marker unchanged.

        surface_metadata: Dict[str, Any] = {}
        if s_seqs is not None:
            surface_metadata["sourceEventSeqs"] = s_seqs
        if s_op is not None:
            surface_metadata["surfaceOp"] = s_op

        data_snapshot = walk_json_value(data, detach=True, undefined_sentinel=UNDEFINED)
        if data_snapshot is UNDEFINED:
            raise ValueError(f'session event "{event_type}" carries non-JSON-serializable data')
        assert_supported_request_header(event_type, data_snapshot, location=f'session event "{event_type}"')

        surface_metadata_snapshot = walk_json_value(
            surface_metadata, detach=True, undefined_sentinel=UNDEFINED
        )
        if surface_metadata_snapshot is UNDEFINED:
            raise ValueError(
                f'session event "{event_type}" carries non-JSON-serializable surface metadata'
            )

        entry = _attachments.get(id(self))
        # The publication boundary is store-owned: only an entry that is mid-append
        # rejects a reentrant append, exactly like reference `entry?.appending`.
        if entry is not None and entry.appending:
            raise RuntimeError("session append cannot reenter while another append is being published")

        # The complete candidate is built and deep-frozen BEFORE surface
        # validation and dispatch resolution, 1:1 with reference
        # `deepFreeze({type, seq, time, data: dataSnapshot, ...surfaceMetadata})`
        # (index.ts:625-631). `data` is the SNAPSHOT itself, never a
        # substitution: a literal JSON `null` payload stays `null` (Python
        # `None`) instead of becoming `{}`.
        candidate: Dict[str, Any] = {
            "type": event_type,
            "seq": len(self._log),
            "time": int(time.time() * 1000),
            "data": data_snapshot,
        }
        if surface_metadata_snapshot:
            candidate.update(surface_metadata_snapshot)

        event: Dict[str, Any] = deep_freeze(candidate)

        self._surface_manager.validate_next(event)

        if entry is not None:
            entry.appending = True

        try:
            callbacks: Optional[List[Callable[..., Any]]] = None
            callback_args = [self, event]
            emit_ctx = entry.emit_ctx if entry is not None else self.ctx

            if entry is not None and emit_ctx is not None:
                callbacks = _collect_session_callbacks(
                    emit_ctx, [entry.carrier, "session/event", *callback_args]
                )

            self._log.append(event)
            self._events_snapshot = None

            if callbacks is not None and entry is not None and emit_ctx is not None:
                _invoke_contained_session_observers(
                    emit_ctx, "session/event", entry.id, callback_args, callbacks
                )

            return event
        finally:
            if entry is not None:
                entry.appending = False
                if entry.detach_requested and not entry.announcing:
                    entry.detach()

    # Convenience appends
    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        surface_op = "append" if is_surface_eligible_type(event_type) else None
        return self.append(event_type, data, surface_op=surface_op)

    def append_user_message(
        self,
        text: Any,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
        source_event_seqs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        msg_id = message_id or f"user-{os.urandom(4).hex()}"
        src = source if (isinstance(source, dict) and "kind" in source) else {"kind": "user"}
        content = [{"type": "text", "text": text}] if isinstance(text, str) else text
        data: Dict[str, Any] = {
            "role": "user",
            "id": msg_id,
            "content": content,
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
        message: Union[Dict[str, Any], str],
        turn: Optional[int] = None,
        step: Optional[int] = None,
        usage: Optional[Dict[str, Any]] = None,
        timing: Optional[Dict[str, Any]] = None,
        interrupted: bool = False,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        msg_copy = dict(message) if isinstance(message, dict) else {"content": message}
        if "id" not in msg_copy:
            msg_copy["id"] = f"assistant-{os.urandom(4).hex()}"
        if "source" not in msg_copy:
            msg_copy["source"] = {"kind": "model", "provider": "mock", "model": "mock"}
        if "role" not in msg_copy:
            msg_copy["role"] = "assistant"
        raw_content = msg_copy.get("content")
        if raw_content is None:
            msg_copy["content"] = []
        elif isinstance(raw_content, str):
            msg_copy["content"] = [{"type": "text", "text": raw_content}]
        elif isinstance(raw_content, list):
            msg_copy["content"] = [
                {"type": "text", "text": item} if isinstance(item, str) else item
                for item in raw_content
            ]

        data: Dict[str, Any] = {
            "turn": turn if turn is not None else 1,
            "step": step if step is not None else 1,
            "message": msg_copy,
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
        name: str = "tool",
        result: str = "",
        turn: Optional[int] = None,
        step: Optional[int] = None,
        timing: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        surface_op: Optional[Union[str, Dict[str, Any]]] = None,
        source_event_seqs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        tool_msg = {
            "id": f"tool-result-{os.urandom(4).hex()}",
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

    def append_request_context(
        self, provider: str, model: str, context_window: Optional[int] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"provider": provider, "model": model}
        if context_window is not None:
            payload["contextWindow"] = context_window
        return self.append("request/context", payload)

    def request_header(self) -> Optional[Dict[str, Any]]:
        """Fold and cache the latest request/header from the event log.

        The folded record is deep-frozen (index.ts:674 wraps the fold in
        `deepFreeze`), so a reader that mutates it cannot desync the cached
        comparisons a later append performs.
        """
        if self._header_fold_seq < len(self._log):
            self._header_fold = deep_freeze(fold_request_header(
                self._log[self._header_fold_seq :], self._header_fold
            ))
            self._header_fold_seq = len(self._log)
        return self._header_fold

    requestHeader = request_header

    def request_context(self) -> Optional[Any]:
        """Fold and cache the latest request/context from the event log.

        Mirrors index.ts:689-696: each record is stored as
        `deepFreeze({ ...event.data })`, so the exposed record is immutable.
        """
        if self._context_fold_seq < len(self._log):
            for event in self._log[self._context_fold_seq :]:
                if event.get("type") == "request/context":
                    self._context_fold = deep_freeze(dict(event.get("data", {})))
            self._context_fold_seq = len(self._log)
        return self._context_fold

    requestContext = request_context

    def derive_messages(self, system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Derive messages array for LLM API call by projecting current surface nodes.
        Cached incrementally: O(ΔN) projection over unseen surface nodes.
        Rebuilds only on surface rewrite (replace_generation change).
        """
        surface = self.surface
        nodes = surface.nodes
        generation = surface.replace_generation

        if generation != self._derived_generation:
            self._derived = []
            self._derived_nodes = 0
            self._derived_generation = generation

        for seq in nodes[self._derived_nodes :]:
            if 0 <= seq < len(self._log):
                msg = self.derive_event_message(self._log[seq])
                if msg is not None:
                    self._derived.append(msg)

        self._derived_nodes = len(nodes)

        # A fresh array per call, holding the SHARED, deep-frozen messages: the
        # reference returns `[...this.derived]`, so a consumer cannot mutate the
        # durable history it was handed (index.ts:744).
        history = list(self._derived)
        if system_prompt is not None:
            return [{"role": "system", "content": system_prompt}] + history
        return history

    deriveMessages = derive_messages

    def derive_event_message(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return derive_event_message(event)

    deriveEventMessage = derive_event_message

    def fork(
        self,
        child_session_id: str,
        boundary: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "Session":
        """
        Backward-compatibility convenience to fork from this session.
        """
        cut = boundary if boundary is not None else len(self._log)
        if cut < 0 or cut > len(self._log):
            raise ValueError(f"fork boundary {cut} out of bounds (0..{len(self._log)})")

        nodes = self.surface.nodes
        surface_nodes_in_cut = [s for s in nodes if s < cut]
        if surface_nodes_in_cut:
            if not tool_pairing_balanced_after(self._log[:cut], surface_nodes_in_cut, surface_nodes_in_cut[-1]):
                raise ValueError("fork boundary is not tool-pairing balanced")

        seed_events = [snapshot_json_value(ev) for ev in self._log[:cut]]
        meta_dict = dict(meta or {})
        meta_dict["parentSession"] = self.id
        meta_dict["seedLength"] = cut
        meta_dict["delegationDepth"] = (getattr(self.header, "delegation_depth", 0) or 0) + 1
        if self.header.cwd is not None:
            meta_dict.setdefault("cwd", self.header.cwd)

        # `version`/`id`/`createdAt` are assembled the way the store assembles
        # them (index.ts:875-885): the validator requires all three, so this
        # convenience cannot hand it a partial record.
        header = SessionHeader.from_dict({"id": child_session_id, **meta_dict})
        return Session(session_id=child_session_id, seed=seed_events, header=header, ctx=self.ctx)

    async def flush(self) -> bool:
        if self.ctx:
            sessions_svc = self.ctx.get("sessions")
            if sessions_svc and hasattr(sessions_svc, "flush"):
                return await sessions_svc.flush(self)
            res = await self.ctx.parallel("session/flush", self)
            return len(res) > 0 if isinstance(res, list) else True
        return False


class SessionStore(Service):
    """
    In-memory session store mounted at `ctx.sessions`.
    1:1 aligned with reference `SessionStore`.
    """

    def __init__(self, ctx: Optional[Any] = None):
        super().__init__(ctx, "sessions")
        self._entries: Dict[str, _SessionStoreEntry] = {}
        self._counter: int = 0
        self._contribute_typert(ctx)

    def _contribute_typert(self, ctx: Optional[Any]) -> None:
        """
        Contribute the live `Session` lookup to the Typert registry, 1:1 with
        reference index.ts:796-804: the store registers, through dependency
        inversion (`ctx.inject(['typert'], ...)`), a lookup whose `parameter` is
        `session`, whose wire identity is `sessionId`, whose canonical type
        symbols are the session host object and its wire id, and whose
        `resolve` reads the live store entry.

        The contribution is an effect of the store's own context, so disposing
        the store's fiber withdraws the lookup again (reference: the inject
        callback's registration is owned by the injecting fiber).
        """
        if ctx is None or not hasattr(ctx, "inject"):
            return

        def contribute(type_ctx: Any) -> None:
            registry = getattr(type_ctx, "typert", None)
            if registry is None:
                return
            lookup = TypertLookupProvider(
                parameter="session",
                wire="sessionId",
                host_type_symbol="@deepseek-ai/dsh-session#Session",
                wire_type_symbol="@deepseek-ai/dsh-session/types#SessionId",
                resolve=lambda session_id: self.get(session_id),
            )
            withdraw = registry.lookups.register("session", lookup)
            if getattr(ctx, "fiber", None) is not None:
                ctx.disposable(withdraw, label="typert.lookups.register('session')")

        ctx.inject(["typert"], contribute)

    def apply(self, ctx: Any = None) -> None:
        target_ctx = ctx or self.ctx
        if target_ctx and not target_ctx.has("sessions"):
            target_ctx.set_service("sessions", self)

    def list(self) -> List[Session]:
        return [entry.session for entry in self._entries.values()]

    def get(self, session_id: str) -> Optional[Session]:
        entry = self._entries.get(session_id)
        return entry.session if entry else None

    class _SessionsDictProxy(dict):
        def __init__(self, store: "SessionStore"):
            super().__init__()
            self._store = store

        def __getitem__(self, key: str) -> Session:
            sess = self._store.get(key)
            if sess is None:
                raise KeyError(key)
            return sess

        def __contains__(self, key: object) -> bool:
            return isinstance(key, str) and self._store.get(key) is not None

        def __iter__(self):
            return iter(self._store._entries.keys())

        def __len__(self) -> int:
            return len(self._store._entries)

        def keys(self):
            return self._store._entries.keys()

        def values(self):
            return [entry.session for entry in self._store._entries.values()]

        def items(self):
            return [(entry.id, entry.session) for entry in self._store._entries.values()]

        def get(self, key: str, default: Any = None) -> Any:
            sess = self._store.get(key)
            return sess if sess is not None else default

    @property
    def _sessions(self) -> Any:
        return self._SessionsDictProxy(self)

    def prepare(
        self,
        session_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Session:
        """
        Build a session WITHOUT entering it into the store.
        1:1 with reference `SessionStore.prepare` (index.ts:861-887), which
        returns the unpublished {@link Session} itself; a caller that wants a
        preparation lifetime wraps it with `SessionPreparation.create`.
        """
        opts = dict(options or {})
        opts.update(kwargs)

        sid: str
        if session_id is None and "id" not in opts:
            while True:
                self._counter += 1
                candidate = SessionId(f"session-{self._counter}")
                if candidate not in self._entries:
                    sid = candidate
                    break
        else:
            # An explicit empty id is a real id, not an absent one: `or` would
            # substitute the fallback for `""` and mint a different session.
            raw_id = session_id if session_id is not None else opts.get("id")
            sid = SessionId(raw_id)

        if sid in self._entries:
            raise ValueError(f'session "{sid}" already exists')

        seed_source = opts.get("seedSource") or opts.get("seed_source")
        if seed_source == "persistence":
            seed = opts.get("seed", [])
            meta = opts.get("meta", {})
            return Session.from_restore(session_id=sid, seed=seed, header=meta, ctx=self.ctx)

        seed = opts.get("seed")
        meta = opts.get("meta") or {}
        parent_session = opts.get("parent_session_id") or meta.get("parentSession")
        if parent_session:
            meta["parentSession"] = parent_session

        header_dict: Dict[str, Any] = {
            "version": SESSION_FORMAT_VERSION,
            "id": sid,
            "createdAt": meta.get("createdAt", meta.get("created_at", int(time.time() * 1000))),
        }
        for k in ("cwd", "parentSession", "seedLength", "origin", "delegationDepth", "agentPreset"):
            if k in meta and meta[k] is not None:
                header_dict[k] = meta[k]

        return Session.create(session_id=sid, seed=seed, header=header_dict, ctx=self.ctx)

    def enter(self, session: Union[Session, SessionPreparation]) -> Callable[[], None]:
        sess = session.session if isinstance(session, SessionPreparation) else session
        sid = sess.id
        carrier = scope_target(sess, scope_of(self.ctx) if self.ctx else None)

        if sid in self._entries:
            raise ValueError(f'session "{sid}" already exists')
        if id(sess) in _attachments:
            raise ValueError(f'session "{sid}" is already attached to a store')

        entry = _SessionStoreEntry(session_id=sid, session=sess, carrier=carrier, emit_ctx=self.ctx)
        self._entries[sid] = entry
        _attachments[id(sess)] = entry

        entered = True

        def detach() -> None:
            nonlocal entered
            if not entered:
                return
            entered = False
            if entry.announcing or entry.appending:
                entry.detach_requested = True
                return
            self._detach_entry(entry)

        # The entry holds the INTERNAL capability the publication paths call to
        # honor a deferred detach; only the returned closure is single-shot
        # (reference `entry.detach = () => this.detachEntered(entry)`).
        entry.detach = lambda: self._detach_entry(entry)
        return detach

    def _detach_entry(self, entry: _SessionStoreEntry) -> None:
        entry.detach_requested = False
        if self._entries.get(entry.id) is not entry:
            return
        del self._entries[entry.id]
        _attachments.pop(id(entry.session), None)
        if entry.announced:
            self._emit_disposed(entry)

    def _emit_disposed(self, entry: _SessionStoreEntry) -> None:
        callback_args = [entry.session]
        emit_ctx = entry.emit_ctx or self.ctx
        if emit_ctx is not None:
            try:
                callbacks = _collect_session_callbacks(
                    emit_ctx, [entry.carrier, "session/disposed", *callback_args]
                )
                _invoke_contained_session_observers(
                    emit_ctx, "session/disposed", entry.id, callback_args, callbacks
                )
            except Exception as err:
                if hasattr(emit_ctx, "logger"):
                    emit_ctx.logger.warn(f'session "{entry.id}": session/disposed dispatch threw: {err}')

    def announce(self, session: Union[Session, SessionPreparation]) -> None:
        sess = session.session if isinstance(session, SessionPreparation) else session
        sid = sess.id
        entry = self._live_entry_for(sess)
        if entry.announced or entry.announcing:
            raise RuntimeError(f'session "{entry.id}" was already announced')

        entry.announced = True
        entry.announcing = True
        callback_args = [sess]
        emit_ctx = entry.emit_ctx or self.ctx

        try:
            if emit_ctx is not None:
                callbacks = _collect_session_callbacks(
                    emit_ctx, [entry.carrier, "session/created", *callback_args]
                )
                for cb in callbacks:
                    try:
                        res = cb(*callback_args)
                        if hasattr(res, "__await__"):
                            import asyncio
                            async def _watch(coro: Any) -> None:
                                try:
                                    await coro
                                except Exception as err:
                                    if hasattr(emit_ctx, "logger"):
                                        emit_ctx.logger.warn(
                                            f'session "{entry.id}": session/created listener rejected: {err}'
                                        )
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    loop.create_task(_watch(res))
                            except Exception:
                                pass
                    except Exception as err:
                        raise err
        finally:
            entry.announcing = False
            if entry.detach_requested and not entry.appending:
                entry.detach()

    def _live_entry_for(self, session: Session) -> _SessionStoreEntry:
        entry = _attachments.get(id(session))
        if entry is None or self._entries.get(entry.id) is not entry:
            raise RuntimeError(f'session "{session.id}" is not live in this store')
        return entry

    def create(
        self,
        session_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Session:
        session = self.prepare(session_id=session_id, options=options, **kwargs)
        detach = self.enter(session)

        # In Cordis, registered as disposable on context effect
        if self.ctx and hasattr(self.ctx, "disposable"):
            self.ctx.disposable(detach, label="sessions.create()")

        try:
            self.announce(session)
        except Exception:
            detach()
            raise

        return session

    def fork(
        self,
        source: Union[str, Session],
        boundary: Optional[int] = None,
        child_session_id: Optional[str] = None,
    ) -> Session:
        """
        Create a live child session from a stable prefix of a live source.
        1:1 aligned with reference `SessionStore.fork`.
        """
        if child_session_id is not None and self.get(child_session_id) is not None:
            raise SessionForkError(f'session "{child_session_id}" already exists', "SESSION_ALREADY_EXISTS")

        live_source = self._resolve_fork_source(source)
        seed = self._fork_seed(live_source, boundary)
        meta_dict: Dict[str, Any] = {
            "parentSession": live_source.id,
            "seedLength": len(seed),
        }
        if live_source.header.cwd is not None:
            meta_dict["cwd"] = live_source.header.cwd

        return self.create(child_session_id, options={"seed": seed, "meta": meta_dict})

    def _resolve_fork_source(self, source: Union[str, Session]) -> Session:
        if isinstance(source, str):
            session = self.get(source)
            if session is None:
                raise SessionForkError(f'session "{source}" not found', "SESSION_NOT_FOUND")
            return session

        live = self.get(source.id)
        if live is None:
            raise SessionForkError(f'session "{source.id}" not found', "SESSION_NOT_FOUND")
        if live is not source:
            raise SessionForkError(f'session "{source.id}" is not the live store instance', "SESSION_NOT_LIVE")
        return source

    def _fork_seed(self, session: Session, requested_boundary: Optional[int]) -> List[Dict[str, Any]]:
        events = session.log if hasattr(session, "log") else session.events
        last_event = events[-1] if events else None

        if requested_boundary is not None:
            boundary = requested_boundary
        else:
            if last_event is None:
                return []
            boundary = last_event.get("seq", len(events) - 1)

        if (
            not isinstance(boundary, int)
            or isinstance(boundary, bool)
            or boundary < 0
            or boundary > 9007199254740991
        ):
            raise SessionForkError(
                f'fork boundary for session "{session.id}" must be a non-negative safe integer, got {boundary}',
                "INVALID_BOUNDARY",
            )

        if boundary >= len(events):
            last_seq = events[-1].get("seq") if events else None
            raise SessionForkError(
                f'fork boundary {boundary} does not exist in session "{session.id}" (last seq: {last_seq if last_seq is not None else "none"})',
                "INVALID_BOUNDARY",
            )

        boundary_event = events[boundary]
        if boundary_event is None or boundary_event.get("seq") != boundary:
            raise SessionForkError(
                f'fork boundary {boundary} does not match a contiguous event seq in session "{session.id}"',
                "INVALID_BOUNDARY",
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
                "OPEN_TURN",
            )

        return [snapshot_json_value(ev) for ev in prefix]

    async def flush(self, session: Optional[Union[Session, SessionPreparation]] = None) -> bool:
        sess = session.session if isinstance(session, SessionPreparation) else session
        # `liveEntryFor`: a detached or prepared object -- or a same-id object that
        # is not this store's live instance -- rejects rather than dispatching.
        entry = self._live_entry_for(sess) if sess is not None else None
        if not self.ctx:
            return False
        carrier = entry.carrier if entry else None
        emit_ctx = entry.emit_ctx if entry else self.ctx

        import inspect
        events_bus = getattr(emit_ctx, "events", None)
        callbacks = []
        if events_bus is not None and hasattr(events_bus, "dispatch"):
            callbacks = list(events_bus.dispatch("parallel", [carrier, "session/flush", sess]))
        elif events_bus is not None and hasattr(events_bus, "_dispatch_hooks"):
            callbacks = events_bus._dispatch_hooks("parallel", "session/flush", [sess], emit_ctx)

        if not callbacks:
            return False

        async def _run(cb: Callable[..., Any]) -> Any:
            res = cb(sess)
            if inspect.isawaitable(res):
                return await res
            return res

        import asyncio
        results = await asyncio.gather(*[_run(cb) for cb in callbacks], return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                raise r
        return len(callbacks) > 0


class SessionService(Session):
    """
    Backward-compatibility wrapper: mounts SessionService as a single-session facade.
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
