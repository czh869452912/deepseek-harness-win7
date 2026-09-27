"""
SQLite durable session-persistence backend for DeepSeek Harness Win7.
Stores SessionHeader and contiguous SessionEvents in an SQLite database.
Shares the live write lifecycle with the JSONL backend.
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session import SessionHeader, SESSION_FORMAT_VERSION
from dsh.session.persistence import (
    SessionInspection,
    SessionLocation,
    SessionPersistence,
    SessionPersistenceSnapshot,
)
from dsh.session.repair import migrate_legacy_event, interrupted_turn_closers


class SqliteSessionPersistence(SessionPersistence):
    """
    SQLite durable session-persistence backend.
    """

    def __init__(
        self,
        db_path: str = ".dsh/sessions/sessions.db",
        ctx: Optional[Any] = None,
    ):
        super().__init__(ctx=ctx)
        self._live_writes = None
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                version INTEGER,
                created_at INTEGER,
                cwd TEXT,
                parent_session TEXT,
                seed_length INTEGER,
                meta_json TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_events (
                session_id TEXT,
                seq INTEGER,
                event_type TEXT,
                event_time INTEGER,
                data_json TEXT,
                surface_op TEXT,
                source_seqs_json TEXT,
                ignorable INTEGER,
                PRIMARY KEY (session_id, seq)
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        if hasattr(self, "_conn") and self._conn:
            try:
                self._conn.close()
            except Exception:
                pass

    def locate(self, meta: SessionHeader) -> SessionLocation:
        return SessionLocation(kind="sqlite", path=self.db_path)

    async def create(self, meta: SessionHeader) -> None:
        if self._prepared is not None:
            self._prepared.assert_writable(meta.id)
        async with self.storage_lock(meta.id):
            if self._prepared is not None:
                self._prepared.assert_writable(meta.id)
            await self._create(meta)
            if self._prepared is not None:
                self._prepared.changed(meta.id)

    async def _create(self, meta: SessionHeader) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO sessions (id, version, created_at, cwd, parent_session, seed_length, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta.id,
                meta.version,
                meta.created_at,
                meta.cwd,
                meta.parent_session,
                meta.seed_length,
                json.dumps(meta.to_dict(), ensure_ascii=False),
            ),
        )
        self._conn.commit()

    async def append(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        from dsh.core.session.json import snapshot_json_value, UNDEFINED
        events = snapshot_json_value(events, UNDEFINED)
        if events is UNDEFINED or not isinstance(events, list):
            raise TypeError('session event batch is not losslessly JSON-serializable')
        if not events:
            return
        if self._prepared is not None:
            self._prepared.assert_writable(session_id)
        async with self.storage_lock(session_id):
            if self._prepared is not None:
                self._prepared.assert_writable(session_id)
            await self._append(session_id, events)
            if self._prepared is not None:
                self._prepared.changed(session_id)

    async def inspect(self, session_id: str, signal: Optional[Any] = None) -> SessionInspection:
        return await self.prepared().inspect(session_id, signal)

    async def load(self, session_id: str) -> SessionInspection:
        return await self.prepared().load(session_id)

    async def _append(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        cur = self._conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if not cur.fetchone():
            meta = SessionHeader(session_id=session_id)
            await self._create(meta)

        with self._conn:
            for ev in events:
                seq = ev.get("seq", 0)
                etype = ev.get("type", "")
                etime = ev.get("time", int(time.time() * 1000))
                data = ev.get("data", {})
                surface_op = ev.get("surfaceOp")
                source_seqs = ev.get("sourceEventSeqs")
                ignorable = 1 if ev.get("ignorable") else 0

                cur.execute(
                    """
                    INSERT OR REPLACE INTO session_events (session_id, seq, event_type, event_time, data_json, surface_op, source_seqs_json, ignorable)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        seq,
                        etype,
                        etime,
                        json.dumps(data, ensure_ascii=False),
                        surface_op,
                        json.dumps(source_seqs) if source_seqs is not None else None,
                        ignorable,
                    ),
                )

    async def read_stored(self, session_id: str) -> SessionInspection:
        cur = self._conn.cursor()
        cur.execute("SELECT meta_json FROM sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
        if not row:
            raise FileNotFoundError(f'persisted session "{session_id}" not found in SQLite db')

        meta = SessionHeader.from_dict(json.loads(row[0]))

        cur.execute(
            """
            SELECT seq, event_type, event_time, data_json, surface_op, source_seqs_json, ignorable
            FROM session_events
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        event_rows = cur.fetchall()
        events: List[Dict[str, Any]] = []

        for r in event_rows:
            ev = {
                "type": r[1],
                "seq": r[0],
                "time": r[2],
                "data": json.loads(r[3]) if r[3] else {},
            }
            if r[4] is not None:
                ev["surfaceOp"] = r[4]
            if r[5] is not None:
                ev["sourceEventSeqs"] = json.loads(r[5])
            if r[6]:
                ev["ignorable"] = True
            events.append(migrate_legacy_event(ev, session_id))

        return SessionInspection(meta=meta, events=events)

    async def repair_tail(self, session_id: str) -> None:
        # SQLite transactions commit complete rows; no JSONL byte tail exists.
        return None

    def _live_session(self, session_id):
        sessions = self.ctx.get('sessions') if self.ctx is not None else None
        return sessions.get(session_id) if sessions is not None else None

    async def _load_unshared(self, session_id: str) -> SessionInspection:
        live = self._live_session(session_id)
        if live is not None:
            events = list(live.events)
            if self._live_writes is not None:
                await self._live_writes.flush(live)
            if interrupted_turn_closers(events):
                raise ValueError('cannot load session while its live turn is open')
            if not events:
                await self.read_stored(session_id)
            return SessionInspection(live.header, events)
        inspection = await self.read_stored(session_id)
        closers = interrupted_turn_closers(inspection.events)
        if closers:
            await self._append(session_id, closers)
            inspection.events.extend(closers)
        return inspection

    async def _inspect_unshared(self, session_id: str) -> SessionInspection:
        live = self._live_session(session_id)
        if live is not None:
            return SessionInspection(live.header, list(live.events))
        inspection = await self.read_stored(session_id)
        inspection.events.extend(interrupted_turn_closers(inspection.events))
        return inspection

    async def read_from(self, session_id: str, from_seq: int) -> SessionInspection:
        if type(from_seq) is not int or from_seq < 0 or from_seq > 9007199254740991:
            raise TypeError('readFrom fromSeq must be a non-negative safe integer')
        inspection = await self.read_stored(session_id)
        return SessionInspection(inspection.meta, [e for e in inspection.events if e['seq'] >= from_seq])

    async def list(self) -> List[SessionHeader]:
        cur = self._conn.cursor()
        cur.execute("SELECT meta_json FROM sessions")
        rows = cur.fetchall()
        headers: List[SessionHeader] = []
        for r in rows:
            try:
                headers.append(SessionHeader.from_dict(json.loads(r[0])))
            except Exception:
                continue
        return headers

    async def list_snapshots(self) -> List[SessionPersistenceSnapshot]:
        snapshots: List[SessionPersistenceSnapshot] = []
        for header in await self.list():
            cur = self._conn.cursor()
            cur.execute("SELECT MAX(seq), MAX(event_time) FROM session_events WHERE session_id = ?", (header.id,))
            r = cur.fetchone()
            max_seq = r[0] if r and r[0] is not None else 0
            max_time = r[1] if r and r[1] is not None else header.created_at
            rev = f"{max_time}:{max_seq}"
            snapshots.append(SessionPersistenceSnapshot(header=header, revision=rev))
        return snapshots


class SqliteSessionPersistencePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-persistence-sqlite`: SQLite durable storage backend.
    """

    id = "session-persistence-sqlite"
    name = "@deepseek-ai/dsh-session-persistence-sqlite"
    inject = []

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        db_path: str = ".dsh/sessions/sessions.db",
    ):
        super().__init__(config)
        cfg = self.config or {}
        self.db_path = str(cfg.get("path", cfg.get("db_path", db_path)))

    def apply(self, ctx: Any) -> None:
        persistence = SqliteSessionPersistence(db_path=self.db_path, ctx=ctx)
        ctx.set_service("session_persistence", persistence)

        ctx.set_service("sessionPersistence", persistence)
        from dsh.session.live_persistence import LivePersistence
        persistence.prepared_cache_size = (self.config or {}).get("preparedSessionCacheSize", 5)
        persistence.prepared()
        persistence._live_writes = LivePersistence(persistence, ctx, (self.config or {}).get("writeBatchMaxDelayMs", 200))
        persistence._live_writes.mount()
