"""
Durable, lifecycle-bound feedback for finalized assistant messages.
Aligned 1:1 with official `@deepseek-ai/dsh-message-feedback/src/index`.

The service inspects persisted Session history and never creates or resumes an
Agent or Session. Every mutation is queued behind that Session's prior
mutation, the sidecar write is fenced by the log lifecycle identity, and the
target log prefix is made durable before the sidecar row moves.
"""

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.core.session.json import deep_freeze
from dsh.core.surface import derive_event_message, is_append_surface_event
from dsh.feedback.message_feedback_spec import (
    message_feedback_domain_spec,
    message_feedback_row_schema,
)

#: Immutable empty list reused only as an input to caller-owned copying.
EMPTY_ITEMS: tuple = ()

#: The one deployment-varying limit, validated at the configuration boundary.
DEFAULT_MAX_NOTE_BYTES = 8192


def resolve_max_note_bytes(value: Any) -> int:
    """Validate the one deployment-varying limit at the configuration boundary."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TypeError(
            "message-feedback: maxNoteBytes must be a positive safe integer, got %s" % _js_string(value)
        )
    return value


def _js_string(value: Any) -> str:
    """Render a config value the way `String(value)` does in the reference."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def snapshot_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Copy and freeze one item before it crosses the service boundary.

    Freezing is the port's `FrozenDict`/`FrozenList` pair: the returned value is
    detached from storage AND immutable, exactly like the reference's
    `Object.freeze` copy.
    """
    copy: Dict[str, Any] = {
        "messageId": item["messageId"],
        "rating": item["rating"],
    }
    if item.get("note") is not None:
        copy["note"] = item["note"]
    copy["version"] = item["version"]
    copy["createdAt"] = item["createdAt"]
    copy["updatedAt"] = item["updatedAt"]
    return deep_freeze(copy)


def snapshot_list(items: Any) -> Dict[str, Any]:
    """Copy and freeze a list response."""
    return deep_freeze({"items": [snapshot_item(item) for item in items]})


def success(value: Any) -> Dict[str, Any]:
    """Build a success branch."""
    return {"ok": True, "value": value}


def rejected(error: Dict[str, Any]) -> Dict[str, Any]:
    """Build a business-failure branch."""
    return {"ok": False, "error": error}


def identity_of(header: Any) -> Dict[str, Any]:
    """Project the Session fields that distinguish one persisted log lifecycle."""
    identity: Dict[str, Any] = {"createdAt": _header_created_at(header)}
    cwd = getattr(header, "cwd", None)
    if cwd is not None:
        identity["cwd"] = cwd
    return identity


def _header_created_at(header: Any) -> Any:
    value = getattr(header, "created_at", None)
    if value is None:
        value = getattr(header, "createdAt", None)
    return value


def _header_id(header: Any) -> Any:
    value = getattr(header, "id", None)
    if value is None and isinstance(header, dict):
        value = header.get("id")
    return value


def same_identity(row: Dict[str, Any], header: Any) -> bool:
    """Whether a stored row belongs to the inspected Session lifecycle."""
    session = row.get("session") or {}
    return session.get("createdAt") == _header_created_at(header) and session.get("cwd") == getattr(
        header, "cwd", None
    )


def same_header_identity(left: Any, right: Any) -> bool:
    """Whether two observations name the same persisted Session lifecycle."""
    return (
        _header_id(left) == _header_id(right)
        and _header_created_at(left) == _header_created_at(right)
        and getattr(left, "cwd", None) == getattr(right, "cwd", None)
    )


def row_snapshot(session: Dict[str, Any], items: Any) -> Dict[str, Any]:
    """Freeze the replacement row so storage-domain never exposes mutable aliases."""
    return deep_freeze({"session": dict(session), "items": [snapshot_item(item) for item in items]})


def next_version() -> str:
    """Generate an opaque equality token for one material mutation."""
    return str(uuid.uuid4())


def _now_ms() -> int:
    return int(time.time() * 1000)


class MessageFeedbackService:
    """
    Storage-domain sidecar service mounted at `ctx.messageFeedback`.
    """

    inject = ["storageDomain", "sessionPersistence", "sessions"]

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        cfg = config or {}
        self.max_note_bytes = resolve_max_note_bytes(cfg.get("maxNoteBytes"))
        self._table: Any = None
        self._domain: Any = None
        self._init_task: Optional[asyncio.Future] = None
        self._operation_tails: Dict[str, asyncio.Future] = {}
        self.mutation_admission_open = True

    async def ensure_initialized(self) -> None:
        """
        Settle the activation-time domain open.

        The reference opens its domain inside `[Service.init]`, i.e. before the
        service can be resolved at all; the port starts that open as the
        plugin's activation task, and every entry point awaits it so a request
        that arrives during activation observes a ready table.
        """
        task = self._init_task
        if task is not None:
            from contextlib import suppress

            with suppress(Exception):
                await asyncio.shield(task)

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Open and own the one message-feedback sidecar domain (idempotent)."""
        if self._domain is not None:
            return
        storage_domain = self.ctx.get("storageDomain") if hasattr(self.ctx, "get") else None
        if storage_domain is None or not hasattr(storage_domain, "open"):
            return
        domain = await storage_domain.open(message_feedback_domain_spec)
        self._domain = domain
        # A pure teardown registration: `effect()` would run the callable as a
        # setup and close the domain immediately.
        if hasattr(self.ctx, "disposable"):
            self.ctx.disposable(lambda: self.dispose(), label="message-feedback.domainClose")
        self._table = domain.table("sessions")

    async def dispose(self) -> None:
        """
        Close the owned sidecar domain: admission stops, every admitted mutation
        drains, and only then does the table go away.
        """
        self.mutation_admission_open = False
        tails = [tail for tail in self._operation_tails.values() if tail is not None]
        if tails:
            await asyncio.gather(*[asyncio.shield(tail) for tail in tails], return_exceptions=True)
        domain = self._domain
        self._domain = None
        if domain is not None:
            await domain.close()

    # ── Remote surface ─────────────────────────────────────────────────────

    async def list(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read feedback belonging to the current persisted Session lifecycle.
        A stale row from a reused Session id is invisible.
        """
        session_id = request.get("sessionId")
        known = await self._inspect_session(session_id)
        if not known["ok"]:
            return known
        row = self._require_table().get(session_id)
        if row is not None and same_identity(row, known["value"].meta):
            items = row.get("items") or EMPTY_ITEMS
        else:
            items = EMPTY_ITEMS
        return success(snapshot_list(items))

    async def put(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or replace feedback for one derived append-origin assistant
        message. Every request must match the addressed item's current version;
        a matching no-op returns the stored item without changing its revision.
        """
        note = self._resolve_note(request.get("note"))
        if not note["ok"]:
            return note
        return await self._enqueue(request.get("sessionId"), self._put_operation(request, note["value"]))

    async def delete(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete one feedback item. Absence is successful regardless of the
        supplied version; an existing item requires an exact version match.
        """
        session_id = request.get("sessionId")

        async def operation() -> Dict[str, Any]:
            known = await self._inspect_session(session_id)
            if not known["ok"]:
                return known
            message_id = request.get("messageId")
            table = self._require_table()
            stored = table.get(session_id)
            current = stored if stored is not None and same_identity(stored, known["value"].meta) else None
            items = (current.get("items") if current else None) or EMPTY_ITEMS
            existing = next((item for item in items if item["messageId"] == message_id), None)
            if existing is None:
                return success({"absent": True})
            if request.get("ifVersion") != existing["version"]:
                return rejected(self._version_conflict(existing))
            remaining = [item for item in items if item is not existing]
            await table.put(session_id, row_snapshot(identity_of(known["value"].meta), remaining))
            return success({"absent": True})

        return await self._enqueue(session_id, operation)

    # ── internals ──────────────────────────────────────────────────────────

    def _sessions(self) -> Any:
        service = self.ctx.get("sessions") if hasattr(self.ctx, "get") else None
        return service

    def _persistence(self) -> Any:
        """
        Resolve the session persistence seam.

        The reference service injects `sessionPersistence`; this port's JSONL and
        SQLite providers register the same seam under `session_persistence`
        (`dsh/session/persistence_jsonl.py`), so both spellings are accepted.
        """
        service = self.ctx.get("sessionPersistence")
        if service is None:
            service = self.ctx.get("session_persistence")
        return service

    async def _inspect_session(self, session_id: Any) -> Dict[str, Any]:
        """
        Resolve a live owner directly; otherwise use the storage catalog as the
        existence authority before inspecting the log. Inspection failures for a
        catalogued Session remain infrastructure failures rather than being
        guessed into the business `session-not-found` branch.
        """
        sessions = self._sessions()
        live = sessions.get(session_id) if sessions is not None and hasattr(sessions, "get") else None
        if live is None:
            snapshots = await self._persistence().list_snapshots()
            listed = any(_header_id(getattr(snapshot, "header", None)) == session_id for snapshot in snapshots)
            live = sessions.get(session_id) if sessions is not None and hasattr(sessions, "get") else None
            if not listed and live is None:
                return rejected({"code": "session-not-found", "sessionId": session_id})
        inspection = await self._persistence().inspect(session_id)
        return success(inspection)

    def _has_feedback_target(self, inspection: Any, message_id: Any) -> bool:
        """Require the exact finalized append-origin assistant message projection."""
        for event in inspection.events:
            if event.get("type") != "assistant/message" or not is_append_surface_event(event):
                continue
            message = derive_event_message(event)
            if (
                isinstance(message, dict)
                and message.get("role") == "assistant"
                and message.get("id") == message_id
            ):
                return True
        return False

    async def _ensure_target_durable(self, inspection: Any) -> Any:
        """
        Put the target log prefix behind a durability barrier before its sidecar.
        A live owner flushes through the SessionStore's canonical checkpoint; a
        cold owner is re-read from the physical durable prefix.
        """
        sessions = self._sessions()
        session_id = _header_id(inspection.meta)
        live = sessions.get(session_id) if sessions is not None and hasattr(sessions, "get") else None
        if live is not None and same_header_identity(getattr(live, "header", None), inspection.meta):
            if not await sessions.flush(live):
                raise RuntimeError(
                    "message-feedback: no durability listener participated for live session '%s'"
                    % session_id
                )
            return await self._persistence().read_from(session_id, 0)
        return await self._persistence().read_from(session_id, 0)

    def _resolve_note(self, note: Any) -> Dict[str, Any]:
        """Validate optional-note semantics and the configured complete UTF-8 byte bound."""
        if note is None:
            return success(None)
        if len(note.strip()) == 0:
            return rejected({"code": "note-blank"})
        actual_bytes = len(note.encode("utf-8"))
        if actual_bytes > self.max_note_bytes:
            return rejected(
                {
                    "code": "note-too-large",
                    "maxBytes": self.max_note_bytes,
                    "actualBytes": actual_bytes,
                }
            )
        return success(note)

    def _version_conflict(self, current: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return the authoritative item needed to reconcile one failed comparison."""
        return {
            "code": "version-conflict",
            "current": None if current is None else snapshot_item(current),
        }

    async def _enqueue(self, session_id: Any, operation: Callable[[], Any]) -> Any:
        """
        Queue a complete read/compare/write mutation behind this Session's prior
        mutation. Admission closes with the domain, so a mutation arriving after
        disposal rejects instead of racing the closing table.
        """
        if not self.mutation_admission_open:
            raise RuntimeError("message-feedback: service is disposing")
        previous = self._operation_tails.get(session_id)
        loop = asyncio.get_running_loop()
        result: asyncio.Future = loop.create_future()

        async def runner() -> None:
            if previous is not None:
                try:
                    await asyncio.shield(previous)
                except Exception:
                    pass
            try:
                value = await operation()
                if not result.done():
                    result.set_result(value)
            except Exception as error:  # noqa: BLE001 - the tail swallows, the caller observes
                if not result.done():
                    result.set_exception(error)

        tail = asyncio.ensure_future(runner())
        self._operation_tails[session_id] = tail

        def _settle(_: Any) -> None:
            if self._operation_tails.get(session_id) is tail:
                self._operation_tails.pop(session_id, None)

        tail.add_done_callback(_settle)
        return await result

    def _put_operation(self, request: Dict[str, Any], note_value: Any) -> Callable[[], Any]:
        async def operation() -> Dict[str, Any]:
            session_id = request.get("sessionId")
            message_id = request.get("messageId")
            known = await self._inspect_session(session_id)
            if not known["ok"]:
                return known
            if not self._has_feedback_target(known["value"], message_id):
                return rejected(
                    {"code": "target-not-found", "sessionId": session_id, "messageId": message_id}
                )

            durable = await self._ensure_target_durable(known["value"])
            if not same_header_identity(durable.meta, known["value"].meta) or not self._has_feedback_target(
                durable, message_id
            ):
                return rejected(
                    {"code": "target-not-found", "sessionId": session_id, "messageId": message_id}
                )

            table = self._require_table()
            stored = table.get(session_id)
            current = stored if stored is not None and same_identity(stored, durable.meta) else None
            items = (current.get("items") if current else None) or EMPTY_ITEMS
            index = next(
                (position for position, item in enumerate(items) if item["messageId"] == message_id),
                -1,
            )
            existing = items[index] if index != -1 else None
            observed = existing["version"] if existing is not None else None
            if request.get("ifVersion") != observed:
                return rejected(self._version_conflict(existing))

            if existing is not None and existing["rating"] == request.get("rating") and existing.get(
                "note"
            ) == note_value:
                return success(snapshot_item(existing))

            now = _now_ms()
            item: Dict[str, Any] = {"messageId": message_id, "rating": request.get("rating")}
            if note_value is not None:
                item["note"] = note_value
            item["version"] = next_version()
            item["createdAt"] = existing["createdAt"] if existing is not None else now
            item["updatedAt"] = now if existing is None else max(now, existing["updatedAt"])

            next_items = list(items)
            if index == -1:
                next_items.append(item)
            else:
                next_items[index] = item
            await table.put(session_id, row_snapshot(identity_of(durable.meta), next_items))
            return success(snapshot_item(item))

        return operation

    def _require_table(self) -> Any:
        """Resolve the initialized durable table or fail a broken service lifecycle."""
        if self._table is None:
            raise RuntimeError("message-feedback: durable domain is not initialized")
        return self._table


#: Alias matching the reference's exported class name.
MessageFeedback = MessageFeedbackService

#: Runtime schema export (the durable row shape).
message_feedback_row = message_feedback_row_schema


class MessageFeedbackPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-message-feedback`: mounts `ctx.messageFeedback`
    and owns the service's durable domain lifecycle.
    """

    id = "message-feedback"
    name = "@deepseek-ai/dsh-message-feedback"
    inject = ["storageDomain", "sessionPersistence", "sessions"]

    def apply(self, ctx: Any, config: Optional[Dict[str, Any]] = None) -> Any:
        merged = dict(self.config)
        if config:
            merged.update(config)
        service = MessageFeedbackService(ctx, merged)
        ctx.set_service("messageFeedback", service)
        ctx.set_service("message_feedback", service)

        # The reference service opens its domain during `[Service.init]`, i.e.
        # as part of the plugin's own activation. The port's activation is
        # synchronous, so the open runs as one task on the active loop and the
        # service's `init()` stays idempotent for direct construction.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
        if loop is not None and not loop.is_closed():
            service._init_task = loop.create_task(service.init())
        return None


__all__ = [
    "DEFAULT_MAX_NOTE_BYTES",
    "EMPTY_ITEMS",
    "MessageFeedbackPlugin",
    "MessageFeedbackService",
    "identity_of",
    "next_version",
    "rejected",
    "resolve_max_note_bytes",
    "row_snapshot",
    "same_header_identity",
    "same_identity",
    "snapshot_item",
    "snapshot_list",
    "success",
]
