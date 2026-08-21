"""
Session query service with SQLite FTS5 index and model-facing search tools.
Aligned 1:1 with official `@deepseek-ai/dsh-session-query-sqlite` and `@deepseek-ai/dsh-tool-session-query`.
"""

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class SessionQueryService:
    """
    Session Query SQLite FTS Service mounted at `ctx.sessionQuery`.
    """

    def __init__(self, ctx: Any, db_path: str = ":memory:"):
        self.ctx = ctx
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                seq INTEGER,
                turn INTEGER,
                step INTEGER,
                event_type TEXT,
                content TEXT,
                time INTEGER
            )
        """)
        try:
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                    session_id,
                    content,
                    content=session_documents,
                    content_rowid=id
                )
            """)
        except Exception:
            # Fallback if fts5 is not compiled in sqlite
            pass
        self._conn.commit()

    def index_event(self, session_id: str, event: Dict[str, Any]) -> None:
        ev_type = event.get("type", "")
        data = event.get("data", {})
        text = ""

        if ev_type == "user/message":
            msg = data.get("message", {})
            text = msg.get("content", "") if isinstance(msg.get("content"), str) else json.dumps(msg.get("content", ""))
        elif ev_type == "assistant/message":
            msg = data.get("message", {})
            text = msg.get("content", "") or ""
        elif ev_type == "tool/result":
            text = data.get("result", "")

        if not text:
            return

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO session_documents (session_id, seq, turn, step, event_type, content, time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                event.get("seq", 0),
                data.get("turn", 0),
                data.get("step", 0),
                ev_type,
                text,
                event.get("time", int(time.time() * 1000)),
            ),
        )
        row_id = cur.lastrowid
        try:
            cur.execute(
                "INSERT INTO session_fts(rowid, session_id, content) VALUES (?, ?, ?)",
                (row_id, session_id, text),
            )
        except Exception:
            pass
        self._conn.commit()

    def search_sessions(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        cur = self._conn.cursor()
        results = []
        try:
            # Try FTS search
            cur.execute(
                """
                SELECT d.session_id, d.seq, d.turn, d.step, d.event_type, d.content, d.time
                FROM session_fts f
                JOIN session_documents d ON f.rowid = d.id
                WHERE session_fts MATCH ?
                LIMIT ?
                """,
                (query, limit),
            )
            rows = cur.fetchall()
        except Exception:
            # Fallback LIKE search
            cur.execute(
                """
                SELECT session_id, seq, turn, step, event_type, content, time
                FROM session_documents
                WHERE content LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", limit),
            )
            rows = cur.fetchall()

        for r in rows:
            results.append({
                "sessionId": r[0],
                "seq": r[1],
                "turn": r[2],
                "step": r[3],
                "eventType": r[4],
                "snippet": r[5][:300] + "..." if len(r[5]) > 300 else r[5],
                "time": r[6],
            })
        return results

    def search_events(self, session_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        cur = self._conn.cursor()
        results = []
        try:
            cur.execute(
                """
                SELECT d.session_id, d.seq, d.turn, d.step, d.event_type, d.content, d.time
                FROM session_fts f
                JOIN session_documents d ON f.rowid = d.id
                WHERE session_fts MATCH ? AND d.session_id = ?
                LIMIT ?
                """,
                (query, session_id, limit),
            )
            rows = cur.fetchall()
        except Exception:
            cur.execute(
                """
                SELECT session_id, seq, turn, step, event_type, content, time
                FROM session_documents
                WHERE content LIKE ? AND session_id = ?
                LIMIT ?
                """,
                (f"%{query}%", session_id, limit),
            )
            rows = cur.fetchall()

        for r in rows:
            results.append({
                "sessionId": r[0],
                "seq": r[1],
                "turn": r[2],
                "step": r[3],
                "eventType": r[4],
                "snippet": r[5][:300] + "..." if len(r[5]) > 300 else r[5],
                "time": r[6],
            })
        return results


class SessionQueryPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-query-sqlite`: Mounts `ctx.sessionQuery` and registers `session_search` / `session_event_search`.
    """

    id = "session-query-sqlite"
    name = "@deepseek-ai/dsh-session-query-sqlite"

    def apply(self, ctx: Any) -> None:
        db_path = self.config.get("path", ":memory:")
        service = SessionQueryService(ctx, db_path=db_path)
        ctx.set_service("sessionQuery", service)

        # Hook session append events to index dynamically
        def on_session_append(subject: Any, event: Dict[str, Any]) -> None:
            sid = getattr(subject, "id", "default-session") if hasattr(subject, "id") else "default-session"
            service.index_event(sid, event)

        ctx.on("session/append", on_session_append)

        # Register tools
        tools_svc = ctx.get("tools")
        if tools_svc:
            tools_svc.register(
                name="session_search",
                description="Search prior sessions in the workspace and return the strongest matching event from each session.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query keywords or phrase."},
                        "limit": {"type": "integer", "description": "Max results to return (default 10)."},
                    },
                    "required": ["query"],
                },
                handler=lambda query, limit=10: json.dumps(service.search_sessions(query, limit=limit), ensure_ascii=False, indent=2),
                execution_mode="parallel",
            )

            tools_svc.register(
                name="session_event_search",
                description="Search prior events in one authorized session.",
                parameters={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Session ID to search within."},
                        "query": {"type": "string", "description": "Search query keywords."},
                        "limit": {"type": "integer", "description": "Max results to return (default 10)."},
                    },
                    "required": ["session_id", "query"],
                },
                handler=lambda session_id, query, limit=10: json.dumps(service.search_events(session_id, query, limit=limit), ensure_ascii=False, indent=2),
                execution_mode="parallel",
            )
