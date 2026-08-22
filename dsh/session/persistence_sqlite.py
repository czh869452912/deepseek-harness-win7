"""
SQLite durable session-persistence backend for DeepSeek Harness Win7.
Stores SessionHeader and contiguous SessionEvents in an SQLite database.
Aligned 1:1 with official `@deepseek-ai/dsh-session-persistence-sqlite`.
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
from dsh.session.repair import migrate_legacy_event


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
        if not events:
            return
        cur = self._conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if not cur.fetchone():
            meta = SessionHeader(session_id=session_id)
            await self.create(meta)

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
        self._conn.commit()

    def _check_interrupted_turn(self, session_id: str, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        open_turn: Optional[int] = None
        for event in events:
            etype = event.get("type")
            if etype == "turn/start":
                open_turn = event.get("data", {}).get("turn", 1)
            elif etype == "turn/end":
                open_turn = None

        if open_turn is not None:
            closer_event: Dict[str, Any] = {
                "type": "turn/end",
                "seq": len(events),
                "time": int(time.time() * 1000),
                "session_id": session_id,
                "data": {
                    "turn": open_turn,
                    "reason": {"kind": "interrupted"},
                },
            }
            return [closer_event]
        return []

    async def load(self, session_id: str) -> SessionInspection:
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
                "session_id": session_id,
                "data": json.loads(r[3]) if r[3] else {},
            }
            if r[4] is not None:
                ev["surfaceOp"] = r[4]
            if r[5] is not None:
                ev["sourceEventSeqs"] = json.loads(r[5])
            if r[6]:
                ev["ignorable"] = True
            events.append(migrate_legacy_event(ev, session_id))

        closers = self._check_interrupted_turn(session_id, events)
        if closers:
            await self.append(session_id, closers)
            events.extend(closers)

        return SessionInspection(meta=meta, events=events)

    async def inspect(self, session_id: str) -> SessionInspection:
        return await self.load(session_id)

    async def read_from(self, session_id: str, from_seq: int) -> SessionInspection:
        inspection = await self.inspect(session_id)
        filtered = [e for e in inspection.events if e.get("seq", 0) >= from_seq]
        return SessionInspection(meta=inspection.meta, events=filtered)

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

        def on_session_event(session: Any, event: Dict[str, Any]) -> None:
            sid = session.id if hasattr(session, "id") else event.get("session_id", "default")
            asyncio.create_task(persistence.append(sid, [event]))

        ctx.on("session/event", on_session_event)
        ctx.effect(persistence.close)
