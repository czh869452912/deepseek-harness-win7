"""
Test harness for the message-feedback official cases, ported 1:1 from
`reference/packages/feedback/message-feedback/tests/helpers.ts`.

The composition is the same one the reference harness builds: the real session
store, a controllable persistence provider, the real storage hub/domain/JSON
backend rooted in a temp directory, and the service under test.
"""

import asyncio
import inspect
import shutil
import tempfile
from typing import Any, Dict, List, Optional

from dsh.cordis.context import Context
from dsh.core.session.session import Session, SessionStore
from dsh.core.session.types import SESSION_FORMAT_VERSION, SessionHeader, SessionId
from dsh.feedback.message_feedback import MessageFeedbackService
from dsh.llm.message import create_assistant_message, create_user_message
from dsh.session.persistence import (
    SessionInspection,
    SessionLocation,
    SessionPersistence,
    SessionPersistenceSnapshot,
)
from dsh.storage.hub import StorageService


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class MessageFixture:
    """One deterministic transcript and the ids its cases address."""

    def __init__(
        self,
        session: Session,
        user_message_id: str,
        assistant_message_ids: List[str],
        empty_assistant_message_id: str,
        replacement_assistant_message_id: str,
    ):
        self.session = session
        self.user_message_id = user_message_id
        self.assistant_message_ids = assistant_message_ids
        self.empty_assistant_message_id = empty_assistant_message_id
        self.replacement_assistant_message_id = replacement_assistant_message_id


def append_message_fixture(session: Session) -> MessageFixture:
    """Append one deterministic transcript used by target-validation tests."""
    session.append("turn/start", {"turn": 1})
    session.append("step/start", {"turn": 1, "step": 1})
    user = create_user_message(
        {
            "content": [{"type": "text", "text": "Question"}],
            "source": {"kind": "user"},
        }
    )
    session.append("user/message", user, surface_op="append")

    first = create_assistant_message(
        {
            "content": [{"type": "text", "text": "First answer"}],
            "source": {"provider": "test", "model": "test"},
        }
    )
    first_event = session.append(
        "assistant/message", {"turn": 1, "step": 1, "message": first}, surface_op="append"
    )
    second = create_assistant_message(
        {
            "content": [{"type": "text", "text": "Second answer"}],
            "source": {"provider": "test", "model": "test"},
        }
    )
    session.append("assistant/message", {"turn": 1, "step": 1, "message": second}, surface_op="append")
    empty = create_assistant_message(
        {
            "content": [],
            "source": {"provider": "test", "model": "test"},
        }
    )
    session.append("assistant/message", {"turn": 1, "step": 1, "message": empty}, surface_op="append")
    session.append("step/end", {"turn": 1, "step": 1})
    session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    replacement = create_assistant_message(
        {
            "content": [{"type": "text", "text": "Model-only replacement"}],
            "source": {"provider": "test", "model": "test"},
        }
    )
    session.append(
        "assistant/message",
        {"turn": 1, "step": 1, "message": replacement},
        surface_op={"op": "replace", "start": first_event["seq"], "end": first_event["seq"]},
        source_event_seqs=[first_event["seq"]],
    )

    return MessageFixture(
        session=session,
        user_message_id=user["id"],
        assistant_message_ids=[first["id"], second["id"]],
        empty_assistant_message_id=empty["id"],
        replacement_assistant_message_id=replacement["id"],
    )


def message_fixture(raw_id: str, created_at: Optional[int] = None, cwd: Optional[str] = None) -> MessageFixture:
    """Construct one cold persistence fixture without publishing a live Session."""
    session_id = SessionId(raw_id)
    header = {
        "version": SESSION_FORMAT_VERSION,
        "id": session_id,
        "createdAt": 1_700_000_000_000 if created_at is None else created_at,
    }
    if cwd is not None:
        header["cwd"] = cwd
    session = Session.create(session_id, [], header)
    return append_message_fixture(session)


class TestPersistence(SessionPersistence):
    """Minimal controllable persistence provider for service-level tests."""

    def __init__(self, ctx: Optional[Any] = None):
        super().__init__(ctx)
        self.supports_raw_artifacts = False
        self.durable: Dict[str, SessionInspection] = {}
        self.logical: Dict[str, SessionInspection] = {}
        self.inspect_failure: Optional[BaseException] = None
        self.inspect_calls = 0
        self.read_from_calls = 0
        self.on_read_from: Optional[Any] = None
        self.on_list_snapshots: Optional[Any] = None

    def locate(self, meta: SessionHeader) -> Optional[SessionLocation]:
        return None

    async def create(self, meta: SessionHeader) -> None:
        return None

    async def append(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        return None

    async def load(self, session_id: str) -> SessionInspection:
        return await self.read_from(session_id, 0)

    async def inspect(self, session_id: str) -> SessionInspection:
        self.inspect_calls += 1
        if self.inspect_failure is not None:
            raise self.inspect_failure
        explicit = self.logical.get(session_id)
        if explicit is not None:
            return explicit
        sessions = self.ctx.get("sessions") if self.ctx is not None else None
        live = sessions.get(session_id) if sessions is not None else None
        if live is not None:
            return SessionInspection(live.header, list(live.events))
        stored = self.durable.get(session_id)
        if stored is None:
            raise RuntimeError("test persistence: session '%s' not found" % session_id)
        return stored

    async def read_from(self, session_id: str, from_seq: int) -> SessionInspection:
        self.read_from_calls += 1
        if self.on_read_from is not None:
            await maybe_await(self.on_read_from())
        stored = self.durable.get(session_id)
        if stored is None:
            raise RuntimeError("test persistence: session '%s' not found" % session_id)
        return SessionInspection(
            stored.meta, [event for event in stored.events if event.get("seq", 0) >= from_seq]
        )

    async def list(self) -> List[SessionHeader]:
        return [inspection.meta for inspection in self.durable.values()]

    async def list_snapshots(self) -> List[SessionPersistenceSnapshot]:
        if self.on_list_snapshots is not None:
            await maybe_await(self.on_list_snapshots())
        return [
            SessionPersistenceSnapshot(value.meta, "test:%d:%d" % (index, len(value.events)))
            for index, value in enumerate(self.durable.values())
        ]

    def persist(self, session: Session) -> None:
        self.durable[session.id] = SessionInspection(session.header, list(session.events))

    def set_durable(self, inspection: SessionInspection) -> None:
        self.durable[inspection.meta.id] = inspection


class TestHarness:
    def __init__(self, ctx: Context, persistence: TestPersistence, root: str, service: MessageFeedbackService):
        self.ctx = ctx
        self.persistence = persistence
        self.root = root
        self.service = service

    async def dispose_feedback(self) -> None:
        await self.service.dispose()

    async def dispose(self) -> None:
        await self.dispose_feedback()
        shutil.rmtree(self.root, ignore_errors=True)

    def expect_item(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not result.get("ok"):
            raise AssertionError("expected feedback item, got %s" % (result.get("error") or {}).get("code"))
        return result["value"]


async def setup_harness(max_note_bytes: int = 64) -> TestHarness:
    """Compose the service over the real storage hub/domain/JSON backend."""
    root = tempfile.mkdtemp(prefix="dsh-message-feedback-test-")
    ctx = Context()
    try:
        store = SessionStore(ctx)
        store.apply(ctx)
        persistence = TestPersistence(ctx)
        ctx.provide("sessionPersistence", persistence)
        StorageService(ctx, root_dir=root)
        service = MessageFeedbackService(ctx, {"maxNoteBytes": max_note_bytes})
        ctx.set_service("messageFeedback", service)
        ctx.set_service("message_feedback", service)
        await service.init()
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return TestHarness(ctx=ctx, persistence=persistence, root=root, service=service)


async def flush_tasks() -> None:
    """Let queued service tasks settle the way `await` on the reference promises does."""
    await asyncio.sleep(0)
