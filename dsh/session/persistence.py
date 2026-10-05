"""
Abstract SessionPersistence Seam mounted at `ctx.session_persistence`.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dsh.core.session import SessionHeader


class SessionFormatUnsupportedError(ValueError):
    """Refusal on loading a log written by a newer/unsupported version."""
    name = 'SessionFormatUnsupportedError'


class SessionPersistenceCorruptionError(ValueError):
    """Error on reading a corrupt log."""
    name = 'SessionPersistenceCorruptionError'


def session_format_version_refusal(session_id: str, version: int) -> str:
    return f'session "{session_id}" uses log format v{version}, which was written by a newer harness build; upgrade the harness to read this session'


class SessionLocation:
    """A backend-resolved local artifact location."""

    def __init__(self, kind: str, path: str):
        self.kind = kind
        self.path = path

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "path": self.path}


class SessionInspection:
    """Immutable logical session inspection result."""

    def __init__(self, meta: SessionHeader, events: List[Dict[str, Any]]):
        self.meta = meta
        self.events = events


class SessionPersistenceSnapshot:
    """Lightweight immutable session summary and revision."""

    def __init__(self, header: SessionHeader, revision: str):
        self.header = header
        self.revision = revision


class SessionPersistence(ABC):
    """
    Abstract seam for durable append-only session storage.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._prepared = None
        self._storage = None
        self._storage_locks = {}
        self.prepared_cache_size = 5

    @abstractmethod
    def locate(self, meta: SessionHeader) -> Optional[SessionLocation]:
        """Resolve backend-specific local artifact location without materializing it."""
        raise NotImplementedError

    @abstractmethod
    async def create(self, meta: SessionHeader) -> None:
        """Register detached metadata; materialize on the first append."""
        raise NotImplementedError

    @abstractmethod
    async def append(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        """Durably append a batch of events in contiguous seq order."""
        raise NotImplementedError

    @abstractmethod
    async def load(self, session_id: str) -> SessionInspection:
        """Load an immutable balanced logical view and commit any required cold crash recovery."""
        raise NotImplementedError

    def storage_lock(self, session_id):
        return self._storage_locks.setdefault(session_id, asyncio.Lock())

    def storage(self):
        from dsh.session.coordinator import PersistenceCoordinator
        if self._storage is None:
            self._storage = PersistenceCoordinator(self)
        return self._storage

    def prepared(self):
        from dsh.session.prepared_persistence import PreparedPersistence
        if self._prepared is None:
            self._prepared = PreparedPersistence(self, self.prepared_cache_size)
        return self._prepared

    async def prepare(self, session_id: str, signal: Optional[Any] = None):
        if hasattr(self, '_load_unshared'):
            return await self.prepared().prepare(session_id, signal)
        # Non-storage test/custom providers retain the minimal preparation seam.
        from dsh.core.session import Session
        from dsh.core.session.preparation import SessionPreparation
        inspection = await self.load(session_id)
        return SessionPreparation.create(Session.from_restore(
            session_id=session_id, seed=inspection.events, header=inspection.meta, ctx=self.ctx))

    async def borrowSession(self, session_id, signal=None):
        return await self.prepared().borrow(session_id, signal)

    @abstractmethod
    async def inspect(self, session_id: str, signal: Optional[Any] = None) -> SessionInspection:
        """Inspect an immutable logical session without committing recovery to disk."""
        raise NotImplementedError

    @abstractmethod
    async def read_from(self, session_id: str, from_seq: int) -> SessionInspection:
        """Read stored events from from_seq onward."""
        raise NotImplementedError

    @abstractmethod
    async def list(self, signal: Optional[Any] = None) -> List[SessionHeader]:
        """List all materialized session headers."""
        raise NotImplementedError

    @abstractmethod
    async def list_snapshots(self, signal: Optional[Any] = None) -> List[SessionPersistenceSnapshot]:
        """List metadata and change tokens for all stored sessions."""
        raise NotImplementedError

    async def listSnapshots(self, signal: Optional[Any] = None) -> List[SessionPersistenceSnapshot]:
        return await self.list_snapshots(signal)
