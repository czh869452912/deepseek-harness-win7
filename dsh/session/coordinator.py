"""
Persistence Coordinator & Write-Behind Manager for Session Storage.
1:1 aligned with official `@deepseek-ai/dsh-session-persistence`.
"""

import asyncio
import hashlib
import time
from typing import Any, Dict, List, Optional
from dsh.core.session import SessionHeader
from dsh.session.persistence import (
    SessionInspection,
    SessionLocation,
    SessionPersistence,
    SessionPersistenceSnapshot,
)


class WriteBehindQueue:
    """Non-blocking queue for serializing asynchronous append operations."""

    def __init__(self, backend: SessionPersistence):
        self.backend = backend
        self._buffers: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        async with self._lock:
            if session_id not in self._buffers:
                self._buffers[session_id] = []
            self._buffers[session_id].extend(events)

    async def flush(self, session_id: Optional[str] = None) -> None:
        async with self._lock:
            if session_id:
                events = self._buffers.pop(session_id, [])
                if events:
                    await self.backend.append(session_id, events)
            else:
                sids = list(self._buffers.keys())
                for sid in sids:
                    events = self._buffers.pop(sid, [])
                    if events:
                        await self.backend.append(sid, events)


class PersistenceCoordinator:
    """
    Coordinates session persistence backends, write-behind queueing, and revision hashing.
    """

    def __init__(self, backend: SessionPersistence, ctx: Optional[Any] = None):
        self.backend = backend
        self.ctx = ctx
        self.queue = WriteBehindQueue(backend)
        self._revisions: Dict[str, str] = {}

    def compute_revision(self, meta: SessionHeader, events: List[Dict[str, Any]]) -> str:
        last_seq = events[-1].get("seq", len(events)) if events else 0
        raw = f"{meta.id}:{meta.version}:{len(events)}:{last_seq}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    async def create(self, meta: SessionHeader) -> None:
        await self.backend.create(meta)
        rev = self.compute_revision(meta, [])
        self._revisions[meta.id] = rev

    async def append(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        await self.queue.enqueue(session_id, events)
        await self.queue.flush(session_id)

    async def load(self, session_id: str) -> SessionInspection:
        await self.queue.flush(session_id)
        inspection = await self.backend.load(session_id)
        rev = self.compute_revision(inspection.meta, inspection.events)
        self._revisions[session_id] = rev
        return inspection

    async def inspect(self, session_id: str) -> SessionInspection:
        await self.queue.flush(session_id)
        inspection = await self.backend.inspect(session_id)
        rev = self.compute_revision(inspection.meta, inspection.events)
        self._revisions[session_id] = rev
        return inspection

    async def list_snapshots(self) -> List[SessionPersistenceSnapshot]:
        headers = await self.backend.list()
        snapshots: List[SessionPersistenceSnapshot] = []
        for h in headers:
            rev = self._revisions.get(h.id)
            if not rev:
                try:
                    inspection = await self.backend.inspect(h.id)
                    rev = self.compute_revision(inspection.meta, inspection.events)
                    self._revisions[h.id] = rev
                except Exception:
                    rev = f"rev-{int(time.time())}"
            snapshots.append(SessionPersistenceSnapshot(header=h, revision=rev))
        return snapshots
